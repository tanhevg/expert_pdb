import logging

import requests

log = logging.getLogger(__name__)


PMC_CONVERTER_URL = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"


def resolve_pmc_id(pmids):
    ret = {}
    pmid_str = ','.join(pmids)
    params= {
        "ids": pmid_str,
        "format": "json",
        "tool": "pmc_id_resolver", 
        "email": 'evgeny@ebi.ac.uk'
    }
    response = requests.get(PMC_CONVERTER_URL, params=params)
    response.raise_for_status()
    payload = response.json()
    for r in payload['records']:
        if 'pmid' in r and 'pmcid' in r:
            ret[r['pmid']] = r['pmcid']
    return ret
