import gradio as gr
from pyecharts.charts import Bar, Line, Pie
from pyecharts import options as opts
from pyecharts.globals import ThemeType
import random
import tempfile
import os
import socket
import pandas as pd
import xalpha as xa
import html
import io
import sys


def create_chart(code):
    """创建指数净值曲线图"""
    zzhli = xa.indexinfo(code)
    zzhli.bcmkset(xa.indexinfo("SH000300"), start="2014-01-01")
    return zzhli.v_netvalue(rendered=False)


def create_holdings():
    """创建持仓组合图"""
    path = "./tests/cmb_holdings.csv"
    from xalpha.record_ext import from_positions, mulfix_pos
    
    read = from_positions(path, skiprows=0)
    sysopen = mulfix_pos(status=read)
    return sysopen.v_positions(rendered=False)


def get_random_line_chart():
    """生成随机折线图"""
    weeks = ['第一周', '第二周', '第三周', '第四周', '第五周']
    users = [random.randint(500, 2000) for _ in range(5)]
    
    return (Line(init_opts=opts.InitOpts(width="800px", height="500px", 
                                          theme=ThemeType.MACARONS, bg_color='white'))
            .add_xaxis(weeks)
            .add_yaxis("活跃用户数", users, is_smooth=True)
            .set_global_opts(title_opts=opts.TitleOpts(title="📈 周活跃用户趋势"),
                           yaxis_opts=opts.AxisOpts(name="用户数"),
                           xaxis_opts=opts.AxisOpts(name="周次"),
                           toolbox_opts=opts.ToolboxOpts(is_show=True))
            .set_series_opts(label_opts=opts.LabelOpts(is_show=True)))


def chart_to_html(chart):
    """将Pyecharts图表转换为HTML"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
        temp_path = f.name
    
    chart.render(temp_path)
    
    with open(temp_path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    os.unlink(temp_path)
    
    fixed_html = html_content.replace(
        '<head>',
        '<head><script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>'
    )
    
    return f"""
    <div style="width:100%; height:550px; border:1px solid #ddd; border-radius:10px; overflow:hidden; background:white;">
        <iframe srcdoc='{html.escape(fixed_html)}' style="width:100%; height:100%; border:none;"
                sandbox="allow-scripts allow-same-origin allow-popups allow-forms"></iframe>
    </div>
    """


def execute_python_code(code):
    """执行Python代码并捕获输出"""
    old_stdout = sys.stdout
    redirected_output = io.StringIO()
    sys.stdout = redirected_output
    try:
        exec(code)
        output = redirected_output.getvalue()
        return output if output else "代码执行成功（无输出）"
    except Exception as e:
        return f"执行错误: {str(e)}"
    finally:
        sys.stdout = old_stdout


def process_chat_message(message):
    """处理聊天消息"""
    if message.startswith("python:"):
        return execute_python_code(message[7:])
    return f"你说: {message}\n\n提示: 输入 'python: 你的代码' 执行Python代码"


def build_charts(selected_types):
    """根据选择的类型构建图表"""
    charts_map = {
        "持仓分布": create_holdings,
        "柱状图": lambda: create_chart("0000922"),
        "折线图": get_random_line_chart
    }
    
    html_parts = []
    for chart_type in selected_types:
        if chart_type in charts_map:
            chart = charts_map[chart_type]()
            html_parts.append(chart_to_html(chart))
    
    if not html_parts:
        return '<div style="height:550px;display:flex;align-items:center;justify-content:center;">请勾选图表</div>'
    
    return "".join(html_parts)


def get_network_info():
    """获取网络信息"""
    try:
        hostname = socket.gethostname()
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return f"WSL IP: {ip}"
    except:
        return "请手动查看WSL IP: ip addr show | grep eth0"


# 创建界面
with gr.Blocks(title="WSL + Pyecharts + 聊天") as demo:
    network_info = get_network_info()
    
    gr.HTML(f"""
    <div style="text-align:center; padding:20px; background:linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius:10px;">
        <h1 style="color:white;">📊 Pyecharts 图表 + 聊天交互</h1>
        <p style="color:white;">{network_info}</p>
        <p style="color:white; font-size:14px;">Windows访问: http://[WSL_IP]:7860 | 本地: http://localhost:7860</p>
    </div>
    """)
    
    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 🎮 控制面板")
            chart_types = gr.CheckboxGroup(
                choices=["持仓分布", "柱状图", "折线图"],
                label="图表类型（可多选）",
                value=["持仓分布"]
            )
            generate_btn = gr.Button("🎨 生成图表", variant="primary")
            
            gr.Markdown("### 💬 聊天")
            chat_input = gr.Textbox(label="输入消息", placeholder="输入消息... 或 'python: 代码'", lines=2)
            chat_send = gr.Button("发送", variant="primary")
            clear_btn = gr.Button("清除历史", variant="secondary")
            
            gr.Markdown("---\n💡 **说明**\n- 柱状图: 中证红利指数\n- 折线图: 随机数据\n- 持仓分布: 持仓组合")
        
        with gr.Column(scale=3):
            gr.Markdown("### 📈 图表区域")
            chart_output = gr.HTML(label="图表")
            
            gr.Markdown("### 💬 对话记录")
            chatbot = gr.Chatbot(label="对话记录", height=300)
            chat_history = gr.State([])
    
    # 事件绑定
    generate_btn.click(
        fn=lambda types: build_charts(types),
        inputs=chart_types,
        outputs=chart_output
    )
    
    def send_message(msg, history):
        if not msg or not msg.strip():
            return history, "", history
        
        user_msg = msg.strip()
        bot_resp = process_chat_message(user_msg)
        
        if gr.__version__.startswith(('4.', '5.', '6.')):
            if not history: history = []
            history.append({"role": "user", "content": user_msg})
            history.append({"role": "assistant", "content": bot_resp})
        else:
            history.append((user_msg, bot_resp))
        
        return history, "", history
    
    chat_send.click(send_message, [chat_input, chat_history], [chatbot, chat_input, chat_history])
    chat_input.submit(send_message, [chat_input, chat_history], [chatbot, chat_input, chat_history])
    
    def clear_history():
        return [], ""
    
    clear_btn.click(clear_history, outputs=[chatbot, chat_input])
    
    demo.load(fn=lambda: build_charts(["持仓分布"]), outputs=chart_output)


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False, debug=True)