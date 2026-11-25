# 发布说明

## GitHub与线上页面的关系

本文件夹用于源码分享和开发协作。现有计算器托管在腾讯云CloudBase静态网站托管，GitHub提交不会自动同步腾讯云；本仓库没有配置自动部署，也未启用本计算器的GitHub Pages。

当前线上地址：

https://xiagu-2026-d3ghwv17l06901ed7-1499999493.tcloudbaseapp.com/index.html

CloudBase环境ID：`xiagu-2026-d3ghwv17l06901ed7`。这是公开标识，不是访问凭据。维护该线上地址需要所有者授予腾讯云部署权限；拿到公开源码链接并不自动获得该权限。

## 发布到原地址

先在本文件夹执行测试并完成开发说明中的人工验收。以下使用此前成功发布所用的CloudBase CLI 3.8.5，需Node.js、npm和网络。每条命令在本文件夹内执行；登录由有权限的账号本人完成。

```sh
node tests/test-fees.cjs
npx --yes --package=@cloudbase/cli@3.8.5 tcb login --flow device
npx --yes --package=@cloudbase/cli@3.8.5 tcb hosting:deploy index.html index.html -e xiagu-2026-d3ghwv17l06901ed7 --safe --verify --json
```

只有确认目标环境和页面后才覆盖发布。发布授权可能过期；遇到 `AUTH_FAILED` 重新登录。不要在GitHub提交账号凭据、设备登录码、`.cloudbase`、`.env`或本地登录缓存。

CLI可能返回上传成功但 `verified:false`。这不等于已完成内容验证；可先将线上 `index.html` 下载为项目临时文件，再比较SHA-256，并用浏览器刷新公开地址检查是否为新版。CDN缓存可能延迟。

```sh
npx --yes --package=@cloudbase/cli@3.8.5 tcb hosting:download index.html verify-remote.html -e xiagu-2026-d3ghwv17l06901ed7 --json
```

例如在PowerShell比较：

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath index.html,verify-remote.html
```

比较完成后不要把临时下载文件提交到仓库。回滚方法是取出上一个确认可用提交中的 `index.html`，重新测试并发布；静态上传本身不提供本应用的版本管理。

## 部署自己的副本

接收方也可以把 `index.html` 部署到自己的静态网站托管服务，不需要原账号凭据。若使用自己的CloudBase环境，将命令中的环境ID改为自己的ID。原腾讯云测试域名可能出现平台访问提示页；源码中没有可关闭该平台提示页的开关，不能通过修改HTML保证消除它。

## 本次交接证据

2026-11-25通过公开地址下载的HTML，与本文件夹 `index.html` 的SHA-256一致。校验值见 `VERSION.json`。该核对只证明本次交接时内容相同，不代表未来会自动同步。
