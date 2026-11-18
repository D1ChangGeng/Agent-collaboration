# 第 65 轮 · 核对后再次占用的处理

Git 读数在下一次显式提交前可能变化。分支核对时已释放，但后来又被检出时，提交按现有删除校验处理。拒绝后的复核显示当次 Git 报告的占用路径，从零选开始。用户释放占用、重新勾选并提交，结果栏显示实际完成的项。

对应 M.02.24。复用既有分支比较、检出检查和提交回执。双语回放实际再检出已经核对过的分支，核对 Git 拒绝及引用保留，随后实际释放并显式提交。 [再次占用](evidence/iteration-63-65-space-zh/i65-space-checkout-occupied-again.jpg) · [提交成功](evidence/iteration-63-65-space-zh/i65-space-checkout-retry-resolved.jpg)
