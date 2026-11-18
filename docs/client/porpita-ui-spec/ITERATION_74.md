# 第 74 轮 · 接管后的分支核对与重试

从接管后的原工作区执行移除。Git 留下未合并引用时，在原复核行显示所属 Host 与实际检出路径，按零选打开。用户显式勾选再处理。

传输中断保留上次路径和选择，暂停包含该分支的提交。原行恢复连接并取得新 Git 读数后，用户可以重新提交。Git 在提交时核对真实占用，拒绝结果回到零选复核。当前选项与两个 Host 的同名引用可独立追踪。

首轮实机中断显示了原始 SSH 连接重置。修订在托管隧道建立时复用 SSH 网络恢复判定，将临时网络错误传给现有复核行。认证失败继续走原有处理。双机回放同时核对断线期间直接配对仍可访问，接管连接恢复时仍是原 Runtime。

每次显式重试开始时清空通知中前一次的失败说明、重试入口与持续显示状态。最终回执只呈现当次结果。首轮复验取得正确 Git 结果，但成功通知合并了同一通知 ID 的旧失败内容，现使用原通知组件刷新该状态。

对应 M.02.33。使用 Windows 和 Linux 上同名、同 HEAD 的测试引用，以实际 Git 结果判定目标主机删除。 [恢复行为](ITERATION_69.md) · [双机回放工具](tools/observe-physical-porpita.cjs)

本轮从工作台的保留分支通知进入复核。断线保持原行焦点，恢复后 Git 实况更新。再次占用触发拒绝，释放并重新选择后成功清理 Linux 引用，Windows 引用保留，成功通知呈现当次结果。 [回放结果](evidence/iteration-72-74-physical-en/physical-porpita-checks.json) · [断线](evidence/iteration-72-74-physical-en/i74-disconnected-branch-review.png) · [成功通知](evidence/iteration-72-74-physical-en/i74-explicit-retry-on-linux.png)
