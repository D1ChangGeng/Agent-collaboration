# 第 67 轮 · 配对主机断线与分支重试

配对主机暂时不可达时，复核留在原行，显示「暂时无法连接主机」，保留上次路径、勾选与焦点。只要待提交选择含该项，提交按钮保持禁用。用户可以核对恢复后的同一配对，或取消勾选该项继续处理其他分支。核对期间沿用行内等待反馈与重复操作限制。

原配对版本随保留记录保存。运行期间来源变化时更新为「主机配对已变化」，仅撤下受影响项。旧主机缺少该读操作时提示在原仓库核对。读取超时和 Git 无法确认引用继续显示可解释的状态。核对结果以当前对话框为有效期。

提交仍由保留分支的原 Host 校验 HEAD 和实际检出。Git 拒绝后，通知提供「复核未删除的分支」，再打开时从零选开始，显示当次拒绝和路径。能完成的提交以 Git 回执为准。对应 M.02.26。 [回放工具](tools/observe-space-remote-checkout.cjs)

初次回放发现订阅式请求在手动断开时丢失错误类型。改用保留错误码的配对单次请求，关闭复核时结束当前行对结果的处理。双语复跑验证断开、恢复、再次占用和显式重试。 [首轮记录](evidence/iteration-66-68-trial/paired-first-run.json) · [断线画面](evidence/iteration-66-68-paired-en/i67-paired-host-offline.png) · [简中重试](evidence/iteration-66-68-paired-zh/i67-paired-host-retry.json)

配对隔离的聚焦测试将同一环境 ID 换成另一个配对版本，验证删除在请求发送前被拒绝（`src/renderer/src/store/slices/worktrees/teardown/force-delete-preserved-branch.test.ts`；[源码覆盖](source-index/module-coverage.csv)）。
