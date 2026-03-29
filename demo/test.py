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


def create_chart(code):
    import xalpha as xa
    import pandas as pd
    zzhli = xa.indexinfo(code)
    # 指数注意需要给定的代码为七位，第一位数字代表市场情况，0 代表沪市， 1 代表深市
    # 本例即为沪市 000922 的指数获取，对应中证红利指数
    # 也可直接 xa.indexinfo("SH000922")
    zzhli.price[zzhli.price["date"] >= "2020-04-11"]
    # 指数的价格表，数据类型为 pandas.DataFrame, 净值栏为初始值归一化的1的值，总值栏对应指数的真实值，注释栏均为空
    zzhli.name, zzhli.code  # 指数类的部分属性
    zzhli.bcmkset(xa.indexinfo("SH000300"), start="2014-01-01")
    # 设定中证红利的比较基准为沪深300指数，以便于接下来更多量化分析
    # 同时设定比较分析的区间段是从13年开始的
    chart = zzhli.v_netvalue(rendered=False)
    return chart # , zzhli.name, zzhli.code

def create_chart2():
    path = "./tests/zhaohang.csv"
    # read = xa.record(path, skiprows=1)
    # sysopen = xa.mulfix(status=read.status, totmoney=150 * 1000)
    # sysopen.combsummary()
    # chart = sysopen.v_positions(rendered=False)

    from xalpha.record_ext import from_positions, mulfix_pos
    read = from_positions(path, skiprows=0)
    sysopen = mulfix_pos(status=read)
    sysopen.combsummary()
    chart = sysopen.v_positions(rendered=False)
    return chart

#######################################################
def create_pyecharts_html(chart_type, chat_input=""):
    """创建Pyecharts图表并返回HTML，同时处理聊天输入"""
    
    # 处理聊天输入
    chat_response = ""
    if chat_input:
        try:
            if chat_input.startswith("python:"):
                code = chat_input[7:]  # 去掉"python:"前缀
                import io
                import sys
                old_stdout = sys.stdout
                redirected_output = io.StringIO()
                sys.stdout = redirected_output
                try:
                    exec(code)
                    chat_response = redirected_output.getvalue()
                except Exception as e:
                    chat_response = f"执行错误: {str(e)}"
                finally:
                    sys.stdout = old_stdout
            else:
                chat_response = f"收到消息: {chat_input}\n提示: 输入 'python: 你的代码' 来执行Python代码"
        except Exception as e:
            chat_response = f"处理出错: {str(e)}"
    
    # 创建临时文件
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False)
    temp_path = temp_file.name
    temp_file.close()
    
    # 根据类型创建图表
    if chart_type == "饼图":
        chart = create_chart2()
    elif chart_type == "柱状图":
        chart = create_chart("0000922")
    elif chart_type == "折线图":
        weeks = ['第一周', '第二周', '第三周', '第四周', '第五周']
        users = [random.randint(500, 2000) for _ in range(5)]
        
        chart = (
            Line(init_opts=opts.InitOpts(
                width="800px",
                height="500px",
                theme=ThemeType.MACARONS,
                bg_color='white'
            ))
            .add_xaxis(weeks)
            .add_yaxis("活跃用户数", users, is_smooth=True)
            .set_global_opts(
                title_opts=opts.TitleOpts(title="📈 周活跃用户趋势"),
                yaxis_opts=opts.AxisOpts(name="用户数"),
                xaxis_opts=opts.AxisOpts(name="周次"),
                toolbox_opts=opts.ToolboxOpts(is_show=True),
            )
            .set_series_opts(label_opts=opts.LabelOpts(is_show=True))
        )

    # 保存图表
    chart.render(temp_path)
    
    # 读取HTML内容
    with open(temp_path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    # 删除临时文件
    os.unlink(temp_path)
    
    # 确保ECharts库正确加载
    fixed_html = html_content.replace(
        '<head>',
        '<head><script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>'
    )
    
    # 使用iframe包装
    import html
    escaped_html = html.escape(fixed_html)
    
    iframe_html = f"""
    <div style="width:100%; height:550px; border:1px solid #ddd; border-radius:10px; overflow:hidden; background:white; box-shadow:0 2px 10px rgba(0,0,0,0.1);">
        <iframe 
            srcdoc='{escaped_html}'
            style="width:100%; height:100%; border:none;"
            sandbox="allow-scripts allow-same-origin allow-popups allow-forms"
        >
        </iframe>
    </div>
    """
    
    return iframe_html, chat_response

def process_chat_message(message):
    """处理单条聊天消息"""
    if message.startswith("python:"):
        code = message[7:]
        try:
            # 捕获执行输出
            import io
            import sys
            old_stdout = sys.stdout
            redirected_output = io.StringIO()
            sys.stdout = redirected_output
            exec(code)
            output = redirected_output.getvalue()
            sys.stdout = old_stdout
            return output if output else "代码执行成功（无输出）"
        except Exception as e:
            return f"执行错误: {str(e)}"
    else:
        return f"你说: {message}\n\n提示: 输入 'python: 你的代码' 来执行Python代码"

def get_network_info():
    try:
        hostname = socket.gethostname()
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return f"WSL IP: {ip}"
    except:
        return "请手动查看WSL IP: ip addr show | grep eth0"

def build_multi_charts(selected_list, chat_input):
    html_parts = []
    for typ in ["饼图", "柱状图", "折线图"]:
        if typ in selected_list:
            html_part, _ = create_pyecharts_html(typ, chat_input)
            html_parts.append(html_part)
    if not html_parts:
        return '<div style="height:550px;display:flex;align-items:center;justify-content:center;font-size:18px;color:#666;">请勾选图表</div>'
    return "".join(html_parts)

# ===================== 界面：只改Radio为CheckboxGroup，其余不动 =====================
with gr.Blocks(title="WSL + Pyecharts + 聊天") as demo:
    network_info = get_network_info()
    
    gr.HTML(f"""
    <div style="text-align:center; padding:20px; background:linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius:10px; margin-bottom:20px;">
        <h1 style="color:white; margin:0;">📊 Pyecharts 图表 + 聊天交互</h1>
        <p style="color:white; opacity:0.9; margin:10px 0 0 0;">{network_info}</p>
        <p style="color:white; opacity:0.8; margin:5px 0 0 0; font-size:14px;">
            Windows访问: http://[WSL_IP]:7860 | 本地访问: http://localhost:7860
        </p>
    </div>
    """)
    
    with gr.Row():
        with gr.Column(scale=1, min_width=300):
            gr.Markdown("### 🎮 控制面板")
            
            # 【唯一改动：Radio → CheckboxGroup】
            chart_types = gr.CheckboxGroup(
                choices=["饼图", "柱状图", "折线图"],
                label="图表类型（可多选）",
                value=["饼图"],
                interactive=True
            )
            
            generate_btn = gr.Button(
                "🎨 生成图表", 
                variant="primary", 
                size="lg"
            )
            
            gr.Markdown("### 💬 聊天对话框")
            chat_input = gr.Textbox(
                label="输入消息",
                placeholder="输入消息... 或输入 'python: 你的代码' 执行Python代码",
                lines=2
            )
            
            with gr.Row():
                chat_send = gr.Button("发送", variant="primary", size="sm")
                clear_btn = gr.Button("清除历史", variant="secondary", size="sm")
            
            gr.Markdown("""
            ---
            **💡 使用说明**
            - 柱状图: 使用xalpha获取中证红利指数
            - 折线图: 随机数据
            - 饼图: 随机数据
            - 聊天: 输入 python: 代码 即可执行
            """)
        
        with gr.Column(scale=3):
            gr.Markdown("### 📈 图表区域")
            chart_output = gr.HTML(label="图表")
            
            gr.Markdown("### 💬 聊天历史")
            import gradio as gr
            gradio_version = gr.__version__
            if gradio_version.startswith(('4.', '5.', '6.')):
                chatbot = gr.Chatbot(label="对话记录", height=300)
            else:
                chatbot = gr.Chatbot(label="对话记录", height=300)
            chat_history = gr.State([])
    
    # 绑定
    generate_btn.click(
        fn=build_multi_charts,
        inputs=[chart_types, gr.State("")],
        outputs=chart_output
    )
    
    def send_message(chat_input, history):
        if not chat_input or not chat_input.strip():
            return history, "", history
        user_message = chat_input.strip()
        bot_response = process_chat_message(user_message)
        if gr.__version__.startswith(('4.', '5.', '6.')):
            if not history: history = []
            history.append({"role": "user", "content": user_message})
            history.append({"role": "assistant", "content": bot_response})
        else:
            history.append((user_message, bot_response))
        return history, "", history
    
    chat_send.click(send_message, [chat_input, chat_history], [chatbot, chat_input, chat_history])
    chat_input.submit(send_message, [chat_input, chat_history], [chatbot, chat_input, chat_history])
    
    def clear_history():
        return [], ""
    clear_btn.click(clear_history, outputs=[chatbot, chat_input])
    
    demo.load(
        fn=build_multi_charts,
        inputs=[chart_types, gr.State("")],
        outputs=chart_output
    )

if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        debug=True,
        theme=gr.themes.Soft()
    )