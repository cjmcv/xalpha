import xalpha as xa
import pandas as pd

# xa.set_display("notebook")

zzhli = xa.indexinfo("0000922")
# 指数注意需要给定的代码为七位，第一位数字代表市场情况，0 代表沪市， 1 代表深市
# 本例即为沪市 000922 的指数获取，对应中证红利指数
# 也可直接 xa.indexinfo("SH000922")

zzhli.price[zzhli.price["date"] >= "2020-04-11"]
# 指数的价格表，数据类型为 pandas.DataFrame, 净值栏为初始值归一化的1的值，总值栏对应指数的真实值，注释栏均为空

zzhli.name, zzhli.code  # 指数类的部分属性

zzhli.bcmkset(xa.indexinfo("SH000300"), start="2014-01-01")
# 设定中证红利的比较基准为沪深300指数，以便于接下来更多量化分析
# 同时设定比较分析的区间段是从13年开始的

zzhli.v_netvalue()
# 指数与基准指数的可视化
# 二者都在研究区间的初始日归一

zzhli.alpha(), zzhli.beta()  # 计算中证红利指数相对于沪深300的 alpha 和 beta 收益

zzhli.correlation_coefficient("2020-01-01")  # 计算两个指数截止2019年底的相关系数