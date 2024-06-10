from chatchat.zhipu import Completion

completion = Completion(model='glm-3-turbo')
r = completion.create('Hi', max_tokens=64)
# {
#     'choices': [
#         {
#             'finish_reason': 'stop', 'index': 0, 'message':
#             {
#                 'content': "Hello 👋! I'm ChatGLM（智谱清言）.",
#                 'role': 'assistant'
#             }
#         }
#     ],
#     'created': 1111, 'id': '2222', 'model': 'glm-3-turbo', 'request_id': '8730203825971097305', 'usage': {
#         'completion_tokens': 39, 'prompt_tokens': 6, 'total_tokens': 45
#     }
# }
print(r)
