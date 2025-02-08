### Large Language Models Python API
<table align="center">
    <tr>
        <th>Vendor</th>
        <th>Model</th>
    </tr>
    <tr>
        <td>DeepSeek</td>
        <td>
            deepseek-chat, deepseek-reasoner, deepseek-coder
        </td>
    </tr>
    <tr>
        <td>百度</td>
        <td>
            ernie-lite-8k, ernie-tiny-8k, ernie-speed-8k, ernie-speed-128k, deepseek-v3, deepseek-r1
        </td>
    </tr>
    <tr>
        <td>阿里巴巴</td>
        <td>
            deepseek-v3, deepseek-r1, deepseek-r1-distill-qwen-1.5b, deepseek-r1-distill-qwen-7b, deepseek-r1-distill-qwen-14b, deepseek-r1-distill-qwen-32b
        </td>
    </tr>
    <tr>
        <td>讯飞</td>
        <td>
            lite, generalv3, pro-128k, generalv3.5, max-32k, 4.0Ultra
        </td>
    </tr>
    <tr>
        <td>腾讯</td>
        <td>
            hunyuan-lite, hunyuan-standard, hunyuan-standard-256K, hunyuan-pro
        </td>
    </tr>
    <tr>
        <td>智谱</td>
        <td>
            glm-4-plus, glm-4-air, glm-4-long, glm-4-flash
        </td>
    </tr>
</table>

### Install
```shell
pip install chatchat
```

### Usage
```shell
# set YOUR secret keys
# tencent
chatchat config tencent.secret_id=YOUR_SECRET_ID
chatchat config tencent.secret_key=YOUR_SECRET_KEY
# baidu
chatchat config baidu.app_id=YOUR_APP_ID
# list info of all supported vendors
chatchat config --list
```
> Refer to [\[examples\]](./examples)

### Sponsor
<table align="center">
    <thead>
        <tr>
            <th colspan="2">公众号</th>
        </tr>
    </thead>
    <tbody align="center" valign="center">
        <tr>
            <td colspan="2"><img src="https://jiauzhang.github.io/ghstatic/images/ofa_m.png" style="height: 196px" alt="AliPay.png"></td>
        </tr>
    </tbody>
    <thead>
        <tr>
            <th>AliPay</th>
            <th>WeChatPay</th>
        </tr>
    </thead>
    <tbody align="center" valign="center">
        <tr>
            <td><img src="https://jiauzhang.github.io/AliPay.png" style="width: 196px; height: 196px" alt="AliPay.png"></td>
            <td><img src="https://jiauzhang.github.io/WeChatPay.png" style="width: 196px; height: 196px" alt="WeChatPay.png"></td>
        </tr>
    </tbody>
</table>
