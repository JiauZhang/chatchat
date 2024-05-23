from chatchat.tencent import Completion

completion = Completion('./data.json')
r = completion.create('你好！')
# {
#     'Response': {
#         'RequestId': 'xxx',
#         'Note': '以上内容为AI生成 ，不代表开发者立场，请勿删除或修改本标记',
#         'Choices': [{
#             'Message': {
#                 'Role': 'assistant',
#                 'Content': '您好，有什么可以帮您的吗？'
#             }, 'FinishReason': 'stop'
#         }],
#         'Created': 111,
#         'Id': 'yyy',
#         'Usage': {
#             'PromptTokens': 222,
#             'CompletionTokens': 333,
#             'TotalTokens': 444
#         }
#     }
# }
print(r)
