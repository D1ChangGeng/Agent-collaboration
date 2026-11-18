# 第 82 轮 · GNOME Orca 成功回执自动播报

继承第 79 轮的真实 Git 回执和通知时序。放开模态遮罩后才发布进度或结果，已完成的短操作可直接呈现结果。成功文案、通知与读屏共用实际 Git 数量。 [第 79 轮](ITERATION_79.md) · [W3C 状态消息说明](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html)

从已选分支和确认按钮出发，经 GNOME 系统通知列表中断，再返回原复核。保留选择和焦点，随后按一次 Enter 并等待结果。验收检查 Orca 的完整语句、发声次数、界面回执和两台主机上的同名引用。

实际按 Super+V 打开系统通知，再按 Escape 回到 Git 对话框，分支仍勾选，焦点仍在确认按钮。一次 Enter 后，GNOME Orca 51.1 自动播报一次「Git branches deleted: 1」，与界面回执一致。Linux SSH 项目中的目标引用删除，Windows 同名引用保留。 [中断画面](evidence/iteration-81-83-gnome-en/i82-review-interrupted.png) · [恢复焦点](evidence/iteration-81-83-gnome-en/i82-review-resumed.json) · [语句](evidence/iteration-81-83-gnome-en/i82-automatic-receipt.json) · [录音](evidence/iteration-81-83-gnome-en/i82-receipt-voice.wav) · [Windows 对端](evidence/iteration-81-83-gnome-en/windows-peer-proof.json)
