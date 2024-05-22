from chatchat.xunfei import Completion

# data.json:
# {
#     "xunfei": {
#         "app_id": "x",
#         "api_secret": "y",
#         "api_key": "z"
#     }
# }
completion = Completion('./data.json')
r = completion.create("请给我详细介绍一下相对论，字数不少于三百字！")
print(r)
