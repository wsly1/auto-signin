# auto-signin

森空岛和库街区的本地批量签到工具。它只读取你已经登录后取得的 token、cred、device_code 等凭据，不包含密码登录、验证码处理或绕过安全校验的逻辑。

## 可视化界面

界面默认把账号配置保存到程序同目录的 `accounts.json`。如果你看到 `[Errno 13] Permission denied: 'accounts.json'`，通常是启动程序时工作目录到了受保护位置；更新后的界面会使用绝对路径，重新运行 `gui_app.py` 即可。

界面里可以完成这些操作：

- 添加森空岛账号
- 添加库街区账号
- 从 Edge 复制库街区请求头后自动导入
- 编辑或删除已保存账号
- 刷新森空岛 `cred/cred_token`
- 保存账号配置到 `accounts.json`
- 试运行，检查配置但不真正签到
- 一键批量签到，并在结果区查看每个账号和角色的结果
- 选中一个账号后单独签到

## 配置文件

默认配置文件是 `accounts.json。这个文件会保存账号凭据，不要上传或分享。

## 森空岛凭据

森空岛 token 怎么拿

登录森空岛网页版后，在网址栏输入，注意要先登录需要签到的账号

https://web-api.skland.com/account/info/hg

返回 JSON 里一般看：

data.content

这个值填到工具里的 token
cred/cred_token 不需要你手动从浏览器里找了。现在工具里已经加了“刷新森空岛凭据”按钮，作用就是用当前有效的网页登录 token 自动换出并保存 cred/cred_token。

具体流程：

浏览器登录第一个森空岛账号。
获取这个账号的 token。
打开工具，添加或编辑这个森空岛账号，只填：
token
森空岛游戏
保存。
选中这个账号，点“刷新森空岛凭据”。
工具会自动请求森空岛接口，把返回的：
data.cred 保存为 cred
data.token 保存为 cred_token
然后你再登录第二个森空岛账号，重复同样步骤。等每个账号都刷新过 cred/cred_token 后，日常签到就不依赖浏览器当前登录哪个账号了。

## 库街区凭据

配置里至少需要填 `token`。开源 H5 方案里 `DevCode` 可以为空，工具也已经把 `device_code/devCode` 改成可选。默认 `game_ids` 是 `[3]`，即鸣潮；战双帕弥什通常是 `2`，可以改成 `[2,3]`。

更省事的方式是在 Edge 登录库街区后：

添加到对话（直接在网址栏输入并回车）
https://wiki.kurobbs.com/mc/home

按 F12。
进 Network / 网络。
上方筛选 Fetch/XHR。
刷新页面。
找名字类似这些的请求：

getPage

role

sign

user

任何点开后请求头里有 Token、Devcode 的请求

点开请求，复制 Token、Devcode后面的字符串
回工具粘贴