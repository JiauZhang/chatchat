import chatchat as cc

# data.json:
#     {
#         "baidu": {
#             "api_key": "x",
#             "secret_key": "y"
#         }
#     }
completion = cc.baidu.Completion('./data.json')
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

history = [
    {
        "role": "user",
        "content": "简单介绍一下你自己",
    },
    {
        "role": "assistant",
        "content": "我是人工智能助手，具备智能问答、自然语言处理等多项功能，致力于为用户提供准确、便捷的解答和服务。",
    }
]
chat = cc.baidu.Chat('./data.json', history=history)
r = chat.chat("说的再详细点！")
print(r)
r = chat.chat("给我举个具体的例子。")
print(r)
