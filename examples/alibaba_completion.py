from chatchat.alibaba import Completion

# {
#     "alibaba": {
#         "api_key": "x",
#     }
# }
completion = Completion()
r = completion.create("简单介绍一下你自己。")
# {
#     'output': {
#         'choices': [{
#             'finish_reason': 'stop',
#             'message': {
#                 'role': 'assistant',
#                 'content': 'xxx'
#             }
#         }]
#     },
#     'usage': {
#         'total_tokens': 11,
#         'output_tokens': 22,
#         'input_tokens': 33
#     },
#     'request_id': 'zzz'
# }
print(r)
