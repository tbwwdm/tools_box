import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
import pandas as pd
from datetime import datetime
import os
from passwd_creat import PasswordGenerator

class PasswordGeneratorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("密码生成器")
        self.root.geometry("800x600")
        
        # 创建密码生成器实例
        self.generator = PasswordGenerator()
        
        # 创建选项卡
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(expand=True, fill='both', padx=10, pady=5)
        
        # 创建三个选项卡页面
        self.single_tab = ttk.Frame(self.notebook)
        self.batch_tab = ttk.Frame(self.notebook)
        self.excel_tab = ttk.Frame(self.notebook)
        
        self.notebook.add(self.single_tab, text='单个密码生成')
        self.notebook.add(self.batch_tab, text='批量密码生成')
        self.notebook.add(self.excel_tab, text='Excel处理')
        
        self.setup_single_tab()
        self.setup_batch_tab()
        self.setup_excel_tab()

    def setup_single_tab(self):
        # 密码长度框架
        length_frame = ttk.LabelFrame(self.single_tab, text="密码设置", padding=10)
        length_frame.pack(fill='x', padx=10, pady=5)
        
        ttk.Label(length_frame, text="密码长度:").pack(side='left')
        self.single_length_var = tk.StringVar(value="8")
        self.single_length_entry = ttk.Entry(length_frame, textvariable=self.single_length_var, width=10)
        self.single_length_entry.pack(side='left', padx=5)
        
        # 生成按钮
        ttk.Button(self.single_tab, text="生成密码", command=self.generate_single_password).pack(pady=10)
        
        # 结果显示区
        result_frame = ttk.LabelFrame(self.single_tab, text="生成结果", padding=10)
        result_frame.pack(fill='both', expand=True, padx=10, pady=5)
        
        self.single_result_text = scrolledtext.ScrolledText(result_frame, height=10)
        self.single_result_text.pack(fill='both', expand=True)

    def setup_batch_tab(self):
        # 密码长度框架
        length_frame = ttk.LabelFrame(self.batch_tab, text="密码设置", padding=10)
        length_frame.pack(fill='x', padx=10, pady=5)
        
        ttk.Label(length_frame, text="密码长度:").pack(side='left')
        self.batch_length_var = tk.StringVar(value="8")
        self.batch_length_entry = ttk.Entry(length_frame, textvariable=self.batch_length_var, width=10)
        self.batch_length_entry.pack(side='left', padx=5)
        
        # IP输入区
        ip_frame = ttk.LabelFrame(self.batch_tab, text="IP地址列表", padding=10)
        ip_frame.pack(fill='both', expand=True, padx=10, pady=5)
        
        self.ip_text = scrolledtext.ScrolledText(ip_frame, height=6)
        self.ip_text.pack(fill='both', expand=True)
        
        # 生成按钮
        ttk.Button(self.batch_tab, text="生成密码", command=self.generate_batch_passwords).pack(pady=10)
        
        # 结果显示区
        result_frame = ttk.LabelFrame(self.batch_tab, text="生成结果", padding=10)
        result_frame.pack(fill='both', expand=True, padx=10, pady=5)
        
        self.batch_result_text = scrolledtext.ScrolledText(result_frame, height=6)
        self.batch_result_text.pack(fill='both', expand=True)

    def setup_excel_tab(self):
        # 密码长度框架
        length_frame = ttk.LabelFrame(self.excel_tab, text="密码设置", padding=10)
        length_frame.pack(fill='x', padx=10, pady=5)
        
        ttk.Label(length_frame, text="密码长度:").pack(side='left')
        self.excel_length_var = tk.StringVar(value="8")
        self.excel_length_entry = ttk.Entry(length_frame, textvariable=self.excel_length_var, width=10)
        self.excel_length_entry.pack(side='left', padx=5)
        
        # 文件选择框架
        file_frame = ttk.Frame(self.excel_tab)
        file_frame.pack(fill='x', padx=10, pady=5)
        
        self.file_path_var = tk.StringVar()
        ttk.Entry(file_frame, textvariable=self.file_path_var, width=50).pack(side='left', padx=5)
        ttk.Button(file_frame, text="选择文件", command=self.select_excel_file).pack(side='left')
        
        # 处理按钮
        ttk.Button(self.excel_tab, text="处理Excel", command=self.process_excel).pack(pady=10)
        
        # 结果显示区
        result_frame = ttk.LabelFrame(self.excel_tab, text="处理结果", padding=10)
        result_frame.pack(fill='both', expand=True, padx=10, pady=5)
        
        self.excel_result_text = scrolledtext.ScrolledText(result_frame, height=10)
        self.excel_result_text.pack(fill='both', expand=True)

    def generate_single_password(self):
        try:
            length = int(self.single_length_var.get())
            self.generator.length = length
            password = self.generator.generate_single_password()
            log_file = self.generator.save_to_log(password)
            
            result_text = f"生成的密码: {password}\n"
            result_text += f"保存到日���文件: {log_file}"
            
            self.single_result_text.delete(1.0, tk.END)
            self.single_result_text.insert(tk.END, result_text)
        except ValueError:
            messagebox.showerror("错误", "请输入有效的密码长度")

    def generate_batch_passwords(self):
        try:
            length = int(self.batch_length_var.get())
            self.generator.length = length
            
            ip_list = self.ip_text.get(1.0, tk.END).strip().split('\n')
            ip_list = [ip.strip() for ip in ip_list if ip.strip()]
            
            if not ip_list:
                messagebox.showwarning("警告", "请输入IP地址")
                return
                
            passwords = self.generator.generate_multiple_passwords(len(ip_list))
            log_file = self.generator.save_to_log(passwords)
            
            result_text = "生成结果:\n"
            for ip, password in zip(ip_list, passwords):
                result_text += f"IP: {ip} -> 密码: {password}\n"
            result_text += f"\n保存到日志文件: {log_file}"
            
            self.batch_result_text.delete(1.0, tk.END)
            self.batch_result_text.insert(tk.END, result_text)
        except ValueError:
            messagebox.showerror("错误", "请输入有效的密���长度")

    def select_excel_file(self):
        file_path = filedialog.askopenfilename(
            filetypes=[("Excel files", "*.xlsx *.xls")]
        )
        if file_path:
            self.file_path_var.set(file_path)

    def process_excel(self):
        try:
            file_path = self.file_path_var.get()
            if not file_path:
                messagebox.showwarning("警告", "请选择Excel文件")
                return
                
            length = int(self.excel_length_var.get())
            self.generator.length = length
            
            # 读取Excel文件
            df = pd.read_excel(file_path)
            if 'IP' not in df.columns:
                messagebox.showerror("错误", "Excel文件必须包含'IP'列")
                return
                
            # 生成密码
            passwords = self.generator.generate_multiple_passwords(len(df))
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # 更新DataFrame
            df['密码'] = passwords
            df['生成时间'] = timestamp
            
            # 保存更新后的Excel文件
            output_file = f"processed_{os.path.basename(file_path)}"
            df.to_excel(output_file, index=False)
            
            result_text = f"处理���成!\n"
            result_text += f"总处理记录数: {len(df)}\n"
            result_text += f"已保存到文件: {output_file}"
            
            self.excel_result_text.delete(1.0, tk.END)
            self.excel_result_text.insert(tk.END, result_text)
            
        except ValueError:
            messagebox.showerror("错误", "请输入有效的密码长度")
        except Exception as e:
            messagebox.showerror("错误", f"处理Excel时出错: {str(e)}")

def main():
    root = tk.Tk()
    app = PasswordGeneratorGUI(root)
    root.mainloop()

if __name__ == '__main__':
    main() 