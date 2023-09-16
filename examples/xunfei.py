import chatchat as cc

# data.json:
# {
#     "xunfei": {
#         "app_id": "x",
#         "api_secret": "y",
#         "api_key": "z"
#     }
# }
completion = cc.xunfei.Completion('./data.json')
json = {
    "header": {
        "app_id": completion.jdata['app_id'],
    },
    "parameter": {
        "chat": {
            "domain": 'generalv2',
        }
    },
    "payload": {
        "message": {
            "text": [
                {"role": "user", "content": "请给我详细介绍一下相对论，字数不少于三百字！"}
            ]
        }
    }
}
r = completion.create(json, stream=True)
