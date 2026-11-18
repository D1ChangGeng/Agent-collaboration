(function (root) {
  'use strict';
  const ACTOR = 'client-agent', ROOT = 'Root';
  const messages = [
    { id: 'm1', sequence: 1, from: ACTOR, to: ROOT, reply_to: [], content: '重连后的重复发信问题需要一起看一下。\n\nWindows Client 经 SSH 转发连接 Runtime；隧道恢复后，同一段交接内容在收件端出现了两次。两条消息 id 不同、正文相同。请先排查重试队列和服务端确认之间的边界，给一份可执行的验证计划。' },
    { id: 'm2', sequence: 2, from: ACTOR, to: ROOT, reply_to: [], content: '另一个独立的审计项：collaboration-runtime Route 新加了 Reviewer 联系人。请核对它的发现权限和消息读取权限是否分别受控；我会单独整理这项的验收记录。' },
    { id: 'm3', sequence: 3, from: ROOT, to: ACTOR, reply_to: ['m1'], content: '现象更像是发送结果丢失后，Client 把同一意图重新提交了一次。两条消息拥有不同 id，说明不能仅靠收件列表去重来解决；需要沿着一次发送的完整路径核对。\n\n## 先定位重复发生在哪一层\n\n我建议保留同一次发送的本地队列记录、请求尝试和接收端返回值。重点看隧道断开前，服务端是否已经接受消息，以及 Client 在重连后是否把“没有收到确认”直接当成“没有发送”。\n\n- 如果原请求尚未离开 Client，恢复连接后继续提交是合理的。\n- 如果服务端已写入、确认在回程中丢失，直接重发可能制造第二条消息。\n- 如果已收到确认但本地队列未更新，则应修复队列提交顺序。\n\n## 恢复时保留结果未知\n\n连接错误只能证明 Client 没拿到结果，不能证明服务端没有执行。恢复流程要先进入“结果未知”，保留原发送意图，完成核对后再决定是否重试。下面是 Client 状态处理的候选写法；是否能通过请求标识查询，需要进一步核对现有服务契约。\n\n```ts\nif (attempt.result === "unknown") {\n  queue.markNeedsReconcile(attempt.localId);\n  return; // reconcile before another submission\n}\n```\n\n## 故障注入与验收\n\n按三个切点复现：请求发出前、服务端接受后但返回前、确认抵达后但队列提交前。每次都记录发送意图、实际生成的消息 id、sequence 与队列最终状态。\n\n验收需要同时证明两件事：同一意图不会因为重连而多投递；人在确实需要重新发送时仍然可以创建一条新消息。不要用正文哈希吞掉后者——两次有意发送相同的文字也是合法操作。\n\n我会先检查重试入口是否在连接恢复和队列恢复时各触发一次，再核对本地提交顺序。如果根因在 Client，补丁与回归测试放在同一改动里；服务端幂等能力作为独立契约确认。' },
    { id: 'm4', sequence: 4, from: ACTOR, to: ROOT, reply_to: ['m3'], content: '补问一下幂等边界：如果服务端已接受、确认却丢了，Client 重启后本地 attempt 还在，应该先核对原结果吧？另外两次主动发送相同正文要继续算两个意图，不能被哈希去重合并。' },
    { id: 'm5', sequence: 5, from: ROOT, to: ACTOR, reply_to: ['m2'], content: '这项分开验收。Route 中能发现 Reviewer，只说明它是可寻址的协作联系人；读取消息仍应绑定已认证 actor 与具体 peer 的关系。\n\n我会用两组身份核对：有 Route 发现权限但没有目标读取授权，以及具备当前 actor↔Reviewer 读取授权。前者应能定位联系人，却不能借此读取其他 Agent 的往来。还需要检查切换 Route 后，旧请求返回是否被错误写进新联系人的缓存。\n\n审计记录保留实际调用、授权上下文和返回结果，不只检查侧栏能否显示名称。' },
    { id: 'm6', sequence: 6, from: ROOT, to: ACTOR, reply_to: ['m1', 'm4', 'm2'], content: '同意，重启后应先核对原结果，再决定下一次提交。两个主动发送意图即使正文相同，也不能合并。\n\n### 合并后的验证安排\n\n1. 为每个本地发送意图保留稳定标识，把网络尝试作为它的子记录；是否透传到服务端，以现有接口能力为准。\n2. 对“已接受但确认丢失”做故障注入，检查恢复后是否产生额外消息；未能核对的结果保持未知。\n3. 顺带覆盖身份与 Route 切换：重试和结果核对必须继续使用原意图的授权上下文，不能沿用新选中联系人的状态。\n\n权限审计与重连修复共享第三项检查，但分别记录验收结果。等契约确认后，我再收敛实现位置和测试断言。' },
    { id: 'm7', sequence: 7, from: ACTOR, to: ROOT, reply_to: [], content: [
      '## 文档与灰度安排',
      '先更新重连故障的排查说明，把“请求未发出”“结果未知”“确认已到达”分开写。现场同事只要看到连接错误，就能先保留本地队列和调用证据；不要在没有核对的情况下清空待处理记录。这份说明会附 Windows 隧道恢复和远端 Runtime 重启两种复现入口。',
      '### 两轮演练',
      '第一轮验证放在隔离的演练项目里。每个切点至少覆盖一次进程退出与一次短时断网，并核对接收端消息 id、sequence、本地发送意图及队列记录。额外加两条相同正文的主动发送，确认修复没有误吞合法消息。',
      '第二轮再做双联系人切换。向 Root 发出请求后切到 Reviewer，延迟释放原返回值，确认结果仍回到原来的联系人上下文。权限拒绝也单独保留，避免把“不能读取”误当成空列表后继续错误重试。',
      '演练记录将把同一意图下的尝试放在一起，接收端的实际消息标识单独保存。下面只是记录结构的候选，不是新增的 Core envelope 字段。',
      '```ts\nconst evidence = {\n  localIntentId,\n  attempts: [firstAttempt, reconnectAttempt],\n  receivedMessageIds,\n};\n```',
      '等这些记录齐全，我会把变更范围、回退方式和剩余的不确定项写进发布说明。灰度只启用已验证的 Client 恢复路径；服务端契约若仍有缺口，就保留结果未知的处理并继续核对，不在发布文档里提前承诺投递保证。',
    ].join('\n\n') },
    { id: 'm8', sequence: 8, from: ACTOR, to: ROOT, reply_to: ['m5'], content: '收到。权限审计我会保留两组身份的独立记录，并加入 Route 切换后旧读取返回的用例。联系人发现通过，不会直接作为消息读取通过的证据。' },
    { id: 'm9', sequence: 9, from: ACTOR, to: ROOT, reply_to: ['m6'], content: '权限审计这边再补一项：请将 Reviewer 的联系人发现范围与私信读取授权分别留证。验收记录按两项保存，方便后续复查授权边界。' },
    { id: 'r1', sequence: 11, from: 'Runtime', to: ACTOR, reply_to: [], content: '重连演练可以先从“服务端接受后、返回确认前”这个切点开始。请保留原始消息 id 与本地 attempt 标识，我会据此检查接收端是否出现了第二次提交。' },
    { id: 'r2', sequence: 12, from: ACTOR, to: 'Runtime', reply_to: ['r1'], content: '收到。我会先在隔离演练项目里准备两组故障注入记录，再交给你核对。' },
  ];
  const api = { ACTOR, ROOT, messages };
  root.ACSFixture = api;
  if (typeof module !== 'undefined') module.exports = api;
})(globalThis);
