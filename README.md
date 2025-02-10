### Large Language Models Python API
<table align="center">
    <tr>
        <th>Vendor</th>
        <th>Model</th>
    </tr>
    <tr>
        <td align="center">DeepSeek</td>
        <td>
            <code>deepseek-chat</code> <code>deepseek-reasoner</code> <code>deepseek-coder</code>
        </td>
    </tr>
    <tr>
        <td align="center">百度</td>
        <td>
            <code>ernie-lite-8k</code> <code>ernie-tiny-8k</code> <code>ernie-speed-8k</code> <code>ernie-speed-128k</code> <code>deepseek-v3</code> <code>deepseek-r1</code>
        </td>
    </tr>
    <tr>
        <td align="center">阿里巴巴</td>
        <td>
            <code>deepseek-v3</code> <code>deepseek-r1</code> <code>deepseek-r1-distill-qwen-1.5b</code> <code>deepseek-r1-distill-qwen-7b</code> <code>deepseek-r1-distill-qwen-14b</code> <code>deepseek-r1-distill-qwen-32b</code>
        </td>
    </tr>
    <tr>
        <td align="center">讯飞</td>
        <td>
            <code>lite</code> <code>generalv3</code> <code>pro-128k</code> <code>generalv3.5</code> <code>max-32k</code> <code>4.0Ultra</code> <code>deepseek-r1</code> <code>deepseek-v3</code>
        </td>
    </tr>
    <tr>
        <td align="center">腾讯</td>
        <td>
            <code>hunyuan-lite</code> <code>hunyuan-standard</code> <code>hunyuan-standard-256K</code> <code>hunyuan-pro</code>
        </td>
    </tr>
    <tr>
        <td align="center">智谱</td>
        <td>
            <code>glm-4-plus</code> <code>glm-4-air</code> <code>glm-4-long</code> <code>glm-4-flash</code>
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
