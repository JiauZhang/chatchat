import json

def load_json(jfile):
    with open(jfile) as jf:
        data = json.load(jf)
    return data

def write_json(jfile, jdata):
    with open(jfile, 'w+') as jd:
        json.dump(jdata, jd, indent=4)