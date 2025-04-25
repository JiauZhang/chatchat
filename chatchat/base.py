import pathlib, os, httpx
from conippets import json

__secret_file__ = os.path.join(str(pathlib.Path.home()), '.chatchat.json')

class Base():
    def __init__(self, vendor, vendor_keys, client_kwargs={}):
        self.vendor = vendor
        if not os.path.exists(__secret_file__):
            json.write(__secret_file__, {})

        secret_data = json.read(__secret_file__)
        self.verify_secret_data(secret_data, self.vendor, vendor_keys)
        self.secret_file = __secret_file__
        self.secret_data = secret_data[self.vendor]
        self.client = httpx.Client(**client_kwargs)

    def verify_secret_data(self, secret_data, vendor, vendor_keys):
        has_vendor = vendor in secret_data
        has_key = True
        if has_vendor:
            vendor_data = secret_data[vendor]
            for key in vendor_keys:
                has_key = has_key and key in vendor_data
        if not (has_vendor and has_key):
            print('You need to configure your target vendor first as bellow.')
            for key in vendor_keys:
                print(f'    chatchat config {vendor}.{key}=YOUR_{key.upper()}')
            exit(-1)
