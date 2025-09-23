from chatchat.tencent import TencentClient

client = TencentClient()
r = client.complete('你好！', model='hunyuan-lite')
# {
#     'id': 'bcfad08f30616a687c14b569313ad6b3',
#     'object': 'chat.completion', 'created': 1758460610,
#     'model': 'hunyuan-lite', 'system_fingerprint': '',
#     'choices': [{
#         'index': 0, 'message': {
#             'role': 'assistant', 'content': '你好！很高兴与你交流。xxx'},
#             'finish_reason': 'stop'
#     }], 'usage': {'prompt_tokens': 4, 'completion_tokens': 33, 'total_tokens': 37},
#     'note': '以上内容为AI生成，不代表开发者立场，请勿删除或修改本标记'
# }
print(r)
