import xml.etree.ElementTree as ET

def parse_body(root_el:ET.Element):
    body = root_el.find('./body')
    assert body is not None
    ret = ET.tostring(body, method='xml')
    print(ret)
    return ret

def parse_abstract(root_el:ET.Element):
    abstract = root_el.find('.//abstract')
    if abstract is None:
        return None
    ret = ET.tostring(abstract, method='xml')
    print(ret)
    return ret

def main():
    filename = '/Users/evgeny/nobackup/expert_pdb/publications/PMC5940772.1/PMC5940772.1.xml'
    jats_root = ET.parse(filename).getroot()
    # body = parse_body(jats_root)
    # abstract = parse_abstract(jats_root)
    body = jats_root.find('./body')
    abstract = jats_root.find('.//abstract')
    short_article = ET.Element('short_article')
    short_article.append(abstract)
    short_article.append(body)
    ET.indent(short_article, ' '*4)
    xml_str = ET.tostring(short_article, 'utf8', method='xml')
    print(xml_str.decode('utf8'))

if __name__ == '__main__':
    main()