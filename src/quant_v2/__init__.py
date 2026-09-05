"""quant_research_v2 —— 个人级可解释投研助手。

分层（依赖方向单向向下，由 ARCH010/011 机械强制）：

    domain  ←  engines / strategies / factors / indicators
       ↑
    adapters（唯一允许碰外部世界的层）
"""

__version__ = "2.0.0"
