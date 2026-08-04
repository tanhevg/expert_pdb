import logging
import logging.config
import os
import pathlib
import typing

import boto3
from botocore import UNSIGNED
from botocore.config import Config

log = logging.getLogger(__name__)


OPEN_PMC_S3_BUCKET_NAME='pmc-oa-opendata'


def configure_logging() -> None:
    config_path = pathlib.Path(__file__).resolve().parents[2] / "log.cfg"
    logging.config.fileConfig(config_path, disable_existing_loggers=False)


def init_s3_client():
    s3_client = boto3.client('s3', config=Config(signature_version=UNSIGNED))
    return s3_client

def list_open_pmc_versions(s3_client, pmc_id:str) -> typing.Iterable[str]:
    bucket_name = OPEN_PMC_S3_BUCKET_NAME
    prefix_search = f"{pmc_id}."
    response = s3_client.list_objects_v2(
        Bucket=bucket_name,
        Prefix=prefix_search,
        Delimiter='/'
    )
    common_prefixes = response.get('CommonPrefixes', [])
    if not common_prefixes:
        log.info("No records found in S3 for %s.", pmc_id)
        return []

    return [cp['Prefix'].rstrip('/') for cp in common_prefixes]

def find_latest_version(versions:typing.Iterable[str]) -> str:
    latest_version = None
    highest_version = -1    
    for v in versions:
        try:
            # Strip trailing slash, split by '.', and grab the last part (the version number)
            version_str = v.split('.')[-1]
            version_num = int(version_str)
            
            if version_num > highest_version:
                highest_version = version_num
                latest_version = v
        except ValueError:
            continue            
    return latest_version

def download_open_pmc_s3(s3_client, pmc_id_version:str, dest_path:pathlib.Path):
    target_dir = dest_path / pmc_id_version
    os.makedirs(target_dir, exist_ok=True)
    pmc_prefix = pmc_id_version + '/'
    
    paginator = s3_client.get_paginator('list_objects_v2')
    pages = paginator.paginate(Bucket=OPEN_PMC_S3_BUCKET_NAME, Prefix=pmc_prefix)
    
    download_count = 0
    dirs_cache = set()
    for page in pages:
        for obj in page.get('Contents', []):
            file_key:str = obj['Key']
            
            # Skip S3 "folder" markers
            if file_key.endswith('/'):
                continue

            assert file_key.startswith(pmc_prefix)
            relative_path = file_key[len(pmc_prefix):]
            
            local_file_path = target_dir / relative_path
            dir_to_make = local_file_path.parent
            if dir_to_make not in dirs_cache:
                dir_to_make.mkdir(parents=True, exist_ok=True)
                dirs_cache.add(dir_to_make)
            
            remote_size = obj.get('Size')
            if local_file_path.exists() and (
                remote_size is None or local_file_path.stat().st_size == remote_size
            ):
                log.info("Already downloaded %s.", relative_path)
                continue

            log.info("Downloading %s...", relative_path)
            s3_client.download_file(OPEN_PMC_S3_BUCKET_NAME, file_key, local_file_path)
            download_count += 1
            
    log.info("Downloaded %d files to '%s'.", download_count, target_dir)


def main():
    configure_logging()
    s3_client = init_s3_client()
    pmc_versions = list_open_pmc_versions(s3_client, 'PMC11370360')
    log.info("Available versions: %s", pmc_versions)
    latest_version = find_latest_version(pmc_versions)
    log.info("Latest version: %s", latest_version)
    download_open_pmc_s3(s3_client, latest_version, pathlib.Path('/tmp/'))


# Example Usage:
if __name__ == "__main__":
    main()
