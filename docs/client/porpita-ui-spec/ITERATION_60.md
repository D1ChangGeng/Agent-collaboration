# 第 60 轮 · 原按钮失效时回到原复核

用户从 Space 打开工作树后，工作树可能已在主窗口或 Git 工具中移动。Windows 基线回放移动实际工作树，证实按钮消失后，状态栏返回仍到达同一 Space。焦点落在「取消」，分支选项与返回前的主窗口活动工作树保持。基线行内仍保留上一次的打开成功提示。 [基线焦点与提示](evidence/iteration-60-62-space-baseline/i60-space-checkout-drift-baseline.jpg)

复用原复核 Dialog、返回应答与按钮焦点。原按钮具备可用状态并确实获得焦点时使用该按钮，移除、禁用或无法聚焦时由「取消」接住。Space 用实际焦点结果应答这一次返回。 [WAI-ARIA Dialog 焦点说明](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/)

对应 M.02.19。复核回放在隐藏 Windows 窗口内核对同窗口标识、原勾选与回退焦点。系统级前台切换、读屏与其他平台继续单列验收。 [简中回退](evidence/iteration-60-62-space-zh/i60-space-fallback-focus.jpg)
