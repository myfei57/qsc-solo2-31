"""进程内组件的公共入口。

对外只导出 ``Line`` 与 ``build_line``：组件各自只暴露状态查询与动作接口，
互相之间不直接引用对方的实现细节，所有跨组件事务都由 ``Line`` 上的动作方法
串起来。
"""

from __future__ import annotations

__version__ = "1.0.0"

from .app import Line, build_line

__all__ = ["Line", "build_line", "__version__"]
