from chatchat.baidu import Completion

# {
#     "baidu": {
#         "api_key": "x",
#         "secret_key": "y"
#     }
# }
completion = Completion()
r = completion.create("简单介绍一下你自己，控制在五十个字之内。")
# {
#     'id': 'xxx',
#     'object': 'chat.completion',
#     'created': xxx,
#     'result': '我是一个热情开朗、善于沟通的AI语言模型。我能够快速准确地回答各种问题，并且可以根据用户需求提供个性化的解决方案。',
#     'is_truncated': False,
#     'need_clear_history': False,
#     'usage': {
#         'prompt_tokens': 18,
#         'completion_tokens': 52,
#         'total_tokens': 70
#     }
# }
print(r)
