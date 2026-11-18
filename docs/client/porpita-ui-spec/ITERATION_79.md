# 第 79 轮 · Git 成功回执自动播报

在第 77 轮，强制删除成功可以从通知列表读出。本轮要求用户完成确认后等待即可听见结果。语音和画面共用同一条实际 Git 回执，成功状态更新不抢焦点。 [上次显式读出](ITERATION_77.md) · [W3C 状态消息说明](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html)

复用 Sonner 的通知和读屏状态区域。复核框退出后，若 Git 仍在处理，呈现一条进行中状态，完成后用同一通知更新结果。若对话框退出时操作已完成，直接发布结果。Git 结果已知时立即交给调用方，通知等待遮罩退场。失败与重试仍使用实际 Git 判定。

Wayland 初版的 Orca 记录把成功与已过期的进度合在同一句。最终实机回放只按一次 Enter 提交，随后 Orca 自动播报一次「Git branches deleted: 1」，与画面一致。跨语言和多个并行操作的通知次序继续按对应条件验收。 [初版语音记录](evidence/iteration-78-80-wayland-trial/i79-stale-progress-speech.json) · [最终播报记录](evidence/iteration-78-80-wayland-en/i79-automatic-receipt.json) · [系统录音](evidence/iteration-78-80-wayland-en/i79-receipt-voice.wav)
