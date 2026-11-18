# 第 59 轮 · 返回入口随复核失效

返回入口只关联当前确认打开工作树的复核。用户结束复核，主工作台随即撤下关联入口。再次打开同一批分支时沿用零选及「取消」初始焦点，完成新的工作树打开后形成新的关联。

Space 关闭、重载或渲染进程退出时，使用现有 renderer 生命周期处理。延迟的返回请求需要当前窗口和原复核同时应答。旧请求以失效结束，保留主工作台的当前选择与实际 Git 引用。

对应 M.02.18。英语和简中回放都触发取消、新复核和关闭。简中额外重载同一 Space 窗口，核对入口撤下与旧请求失效。另一次清理回归验证提交即撤下返回入口，Git 确认删除所选分支。 [主窗口关闭态](evidence/iteration-57-59-space-en/i59-space-return-lifetime.png) · [简中断言](evidence/iteration-57-59-space-zh/space-branch-review-checks.json) · [提交回归断言](evidence/iteration-57-59-space-en/regression-54-56-checks.json)
