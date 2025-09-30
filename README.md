### Large Language Models Python API
<table align="center">
    <tr>
        <th>Vendor</th>
        <th>Model</th>
    </tr>
    <tr>
        <td align="center">Google</td>
        <td>
            <code>gemini-2.5-flash</code>
        </td>
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
            <code>ernie-lite-8k</code> <code>ernie-tiny-8k</code> <code>ernie-speed-8k</code> <code>ernie-speed-128k</code>
        </td>
    </tr>
    <tr>
        <td align="center">阿里巴巴</td>
        <td>
            <code>qwen3-max</code> <code>qwen-plus</code> <code>qwen-flash</code> <code>qwen-turbo</code>
        </td>
    </tr>
    <tr>
        <td align="center">讯飞</td>
        <td>
            <code>lite</code> <code>generalv3</code> <code>pro-128k</code> <code>generalv3.5</code> <code>max-32k</code> <code>4.0Ultra</code>
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

### Chat in the Terminal
```shell
$ chatchat run baidu ernie-lite-8k
user> http://github.com/JiauZhang/chatchat 这个网址是干啥的？
assistant> 这个网址 <http://github.com/JiauZhang/chatchat> 是一个指向GitHub上的一个开源项目的链接。

"chatchat" 看起来像是一个项目名称或别名，由 "JiauZhang" 创建并托管在GitHub上。
GitHub是一个流行的代码托管和协作平台，允许开发者存储、分享和协作开发代码。

要了解这个网址具体是干什么的，你可以访问该链接并查看项目详情。
通常，项目页面会包含项目的描述、代码、文档、问题跟踪等。通过查看这些信息，
你可以了解该项目的目的、功能、使用方法等。

请注意，由于这是一个开源项目，其具体内容和用途可能因项目而异。
如果你对特定项目或其用途有更多疑问，建议直接访问GitHub上的项目页面或查看相关文档和说明。
user> ^D

$ chatchat run google gemini-2.0-flash --proxy YOUR_PROXY
user> Introduce yourself briefly.
assistant> Hello! I am a large language model, trained by Google.
I am designed to provide information and complete tasks based on the prompts I receive.
I can generate text, translate languages, write different kinds of creative content,
and answer your questions in an informative way. How can I help you today?
user> ^D
```

### Usage
```shell
# set YOUR secret keys
# tencent
chatchat config tencent.api_key=YOUR_API_KEY
# baidu
chatchat config baidu.api_key=YOUR_API_KEY
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
