# 07｜身份、权限与内容安全

## 身份与信任链

旧 stdio/OAuth/owner binding 是权威入口，新 HTTP facade 复用同一 subject/tenant/actor resolver。Bearer 凭据必须绑定 installation/audience；浏览器使用受控授权流或插件 worker 代理，不把长期 Token 放在 URL、SSE query、localStorage 或消息正文。禁止“声明 sender”字段；服务器注入作者。

受信 Client 不需要 Slot，但不得因缺 Slot 提权。管理权限不等于查看所有协作者私信。聊天记录、正文检索、未读总数、附件、错误信息和 event replay 都必须按实际参与者/已授权委托裁剪。

## Session 接入

注册 receiver 来自真实 Node/Host，不从模型提供的 Session ID 认领身份。receiver 所有权、host fingerprint、binding epoch、provider generation、授权有效性在 handoff 前重验。更换凭据/角色后旧连接工具发现和实际调用必须一致失效。

无原生幂等能力的 PTY 通路必须显式降级。终端输出中“我是 Root”或“已接收 msg-x”均是内容，不是信任证据。Hook 要验证进程、channel 和事件代次，不接纳任意本地程序伪造的状态。

## 人类审批

ACS 可以发送“该接收者在等待审批”的 system notice，或向真正决策者传递 Agent 的问题。不能把审批界面翻译成普通消息后自动点击同意；不能以用户角色注入消息绕过 Harness approval policy。Native approval ID/nonce/turn/权限归原宿主，集成层只做受权 delegate。延迟回复命中过期 approval 必须拒绝。

## 事件与检索防泄漏

每次 emit/read/replay 重新校验 auth revision。仅过滤建立订阅时权限不够。权限失效时发送不含私有标识的 control invalidation/终止流；客户端清除对应缓存。已经合法交付到用户设备的数据无法远程“收回”，不得作此承诺。

对不存在与无权访问的资源返回同一 not_found 风格；diagnostic 管理者也不默认获得正文。cursor 签名绑定 actor/project/filter/auth revision，不能拿另一个人的 cursor 读取其历史或从全局序号推算私信量。

## 附件与输出

上传采用 reservation→流式写入→digest/size/content-type 验证→ready，未 ready 不可随消息提交。附件 message 关联成功后按消息 ACL 读取；暂存由上传者私有，不能凭文件 ID 或 digest 猜到下载链接。默认禁止服务端抓取任意 URL，避免 SSRF；Source 文件引用沿用既有文件权限和位置语义。

按扩展名/Content-Type 都不可信原则处理；HTML/SVG/Markdown 的执行和渲染留给受限客户端策略。消息中路径只作为文本，不能自动触发文件读写/执行。原生工具和推理内容不默认归档到 ACS；诊断日志不收集其全文。

## 管理接口

恢复、绑定变更、附件删除/保留策略等有副作用动作需要明确权限与版本条件；权限拒绝失败不留 Native 副作用。配额在提交前检查；已接受内容不因后续配额压力丢弃。日志只含 opaque handle/digest 和必要技术状态；原始敏感证据由授权人控制保存。

## 插件 hook 不是安全边界的替代物

只有真正的原生 handoff 入口受权并持久 fence，才能承诺拒绝旧代次或撤销请求。UI action replacement、发送前提示或可超时插件 hook 不能单独承担这一保证；执行时核对其所有路径覆盖和失败策略。若公开宿主 API 无法提供受信准入，标 host_extension_required，不能用“通常能拦住”签署安全资格。
