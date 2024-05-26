import json, pathlib, os

class Base():
    def __init__(self):
        dot_secret_file = os.path.join(
            str(pathlib.Path.home()),
            '.chatchat.json',
        )
        if not os.path.exists(dot_secret_file):
            self.write_json(dot_secret_file, {})

        self.secret_data = self.load_json(dot_secret_file)
        self.secret_file = dot_secret_file

    def verify_secret_data(self, plat, keys):
        has_plat = plat in self.secret_data
        has_key = True
        if has_plat:
            plat_data = self.secret_data[plat]
            for key in keys:
                has_key = has_key and key in plat_data
        if not (has_plat and has_key):
            print('\nYou must set:')
            for key in keys:
                print(f'\tchatchat config {plat}.{key}=YOUR_{key.upper()}')
            exit(-1)

    def load_json(self, jfile):
        with open(jfile) as jf:
            data = json.load(jf)
        return data

    def write_json(self, jfile, jdata):
        with open(jfile, 'w+') as jd:
            json.dump(jdata, jd, indent=4)