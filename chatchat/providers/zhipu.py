from chatchat.client import BaseClient

class ZhipuClient(BaseClient):
    def __init__(self, model=None, instruction=None, http_options={}):
        super().__init__(
            'zhipu',
            'https://open.bigmodel.cn/api/paas/v4',
            http_options=http_options, model=model, instruction=instruction,
        )

    def build_client_messages(self, model, messages, generation_options):
        jmsg = super().build_client_messages(model, messages, generation_options)
        thinking = 'enabled' if generation_options.get('thinking') else 'disabled'
        jmsg['thinking'] = {'type': thinking}
        return jmsg
