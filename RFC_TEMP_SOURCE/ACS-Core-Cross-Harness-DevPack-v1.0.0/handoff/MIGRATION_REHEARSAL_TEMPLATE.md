# 迁移演练记录

源/目标 schema，实际数据库版本，隔离 namespace，backup digest，恢复验证命令，迁移 SQL/manifest digest，行数与 message/author/reply/key 不变校验，投影回填 checkpoint，中断位置与续跑结果，旧 reader 兼容，应用回滚策略，未决 Native operation 的调和方式。

必须记录：是否有在库恢复时已经发生的外部副作用；怎样保证没有因回滚重新提交同一输入。没有生产权限时不能在生产执行。
