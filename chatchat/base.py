import json

class Base():
    def __init__(self):
        ...

    def load_json(self, jfile):
        with open(jfile) as jf:
            data = json.load(jf)
        return data

    def write_json(self, jfile, jdata):
        with open(jfile, 'w+') as jd:
            json.dump(jdata, jd, indent=4)