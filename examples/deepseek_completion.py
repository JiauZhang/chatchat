from chatchat.deepseek import Completion

completion = Completion()
model_info = completion.model_list()
print(model_info)

r = completion.create('Hi', max_tokens=32)
# {
#     'id': 'xxx',
#     'choices': [
#         {
#             'index': 0,
#             'message': {
#                 'content': 'Hello! How can I assist you today? If you have any questions or need information, feel free to ask.',
#                 'role': 'assistant'
#             },
#             'finish_reason': 'stop',
#             'logprobs': None
#         }
#     ],
#     'created': 111,
#     'model': 'deepseek-chat',
#     'system_fingerprint': 'yyy', 'object': 'chat.completion', 'usage': {
#         'prompt_tokens': 8, 'completion_tokens': 23, 'total_tokens': 31
#     }
# }
print(r)
