from chatchat.google import Completion

completion = Completion()
r = completion.create('Hi')
# {
#     'choices': [{
#         'finish_reason': 'stop', 'index': 0, 'message': {
#             'content': 'Hi there! How can I help you today?', 'role': 'assistant'
#         }
#     }],
#     'created': 1758548621, 'id': 'jVLRaISnIs65vdIPubGzyAU',
#     'model': 'gemini-2.5-flash-lite', 'object': 'chat.completion',
#     'usage': {'completion_tokens': 10, 'prompt_tokens': 2, 'total_tokens': 12}
# }
print(r)