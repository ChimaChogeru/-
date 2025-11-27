import streamlit as st
from datetime import date, timedelta, time
import pandas as pd
import calendar
import os
from google import genai
from google.genai.errors import APIError
from dotenv import load_dotenv

load_dotenv()

import streamlit as st
from datetime import date, timedelta, time
import pandas as pd
import calendar
import os
from google import genai
from google.genai.errors import APIError 

# --- クラス定義 (データ構造) ---
class Employee:
    def __init__(self, name, available_days, start_time, end_time, 
                 hourly_wage, rest_time_hours, unavailable_dates, desired_monthly_income, tasks):
        self.name = name
        self.available_days = available_days 
        self.start_time = start_time
        self.end_time = end_time
        self.hourly_wage = hourly_wage
        self.rest_time_hours = rest_time_hours 
        self.unavailable_dates = unavailable_dates
        self.desired_monthly_income = desired_monthly_income if desired_monthly_income is not None else 0
        self.tasks = tasks 
    
    def to_dict(self):
        return {
            "name": self.name,
            "available_days": self.available_days,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "hourly_wage": self.hourly_wage,
            "rest_time_hours": self.rest_time_hours,
            "unavailable_dates_input": "\n".join([d.strftime('%Y-%m-%d') for d in self.unavailable_dates]),
            "desired_monthly_income": self.desired_monthly_income,
            "tasks": self.tasks
        }

# --- プロンプト生成関数  ---
def create_shift_prompt(employees, job_requirements, shift_period_start, shift_period_end):
    shift_period_str = f"{shift_period_start.year}年{shift_period_start.month}月{shift_period_start.day}日から{shift_period_end.year}年{shift_period_end.month}月{shift_period_end.day}日まで"
    
    prompt = "あなたは優秀なシフト作成AIです。以下の制約条件と従業員データに基づき、公平かつ最適なシフト表を**Markdown形式の表**で作成してください。従業員が目標月収を設定している場合は、それにできるだけ近づくようにシフト時間を調整してください。なお、**休憩時間は労働時間に含めず、純粋な勤務時間のみを計算に含めてください。**\n\n"
    
    prompt += f"# 📅 シフト期間\n{shift_period_str} のシフトを作成してください。\n\n"
    
    prompt += "# 🛠️ 日々の業務要件\n毎日、以下の業務について指定された最低人数を、指定された時間帯に配置する必要があります。\n"
    for job, req in job_requirements.items():
        prompt += f"* **{job}**: 最低 {req['min_people']} 名必要。**必須時間帯: {req['start_time']} から {req['end_time']} まで。**\n"
    prompt += "\n"

    prompt += "# 👤 従業員と制約\n"
    for emp in employees:
        time_diff = pd.to_datetime(str(emp.end_time)) - pd.to_datetime(str(emp.start_time))
        work_hours = time_diff.total_seconds() / 3600
        actual_work_hours = work_hours - emp.rest_time_hours
        
        unavailable_dates_str = ", ".join([d.strftime('%Y-%m-%d') for d in emp.unavailable_dates]) if emp.unavailable_dates else "なし"
        
        income_str = f"{emp.desired_monthly_income:,} 円" if emp.desired_monthly_income > 0 else "設定なし (任意)"
        
        prompt += f"--- {emp.name} ---\n"
        prompt += f"* **時給**: {emp.hourly_wage:,} 円\n"
        prompt += f"* **目標月収**: {income_str}\n"
        prompt += f"* **勤務可能時間帯**: {emp.start_time.strftime('%H:%M')} - {emp.end_time.strftime('%H:%M')} (休憩 {emp.rest_time_hours:.2f}時間 / 実働 {actual_work_hours:.2f}時間)\n"
        prompt += f"* **入れる曜日**: {', '.join(emp.available_days)}\n"
        prompt += f"* **担当可能業務**: {', '.join(emp.tasks)}\n"
        prompt += f"* **入れない日（完全不可）**: {unavailable_dates_str}\n"
    
    prompt += "\n# 📝 出力形式の指示\n"
    prompt += "以下の形式で、期間内のすべての日付を含めた一つのMarkdownテーブルを出力してください。\n"
    job_names = job_requirements.keys()
    prompt += "日付 | 曜日 | " + " | ".join(job_names) + "\n"
    prompt += "--- | --- | " + " | ".join(["---"] * len(job_names)) + "\n"
    
    prompt += "\n\n# 💰 従業員別 勤務と収入サマリー\n"
    prompt += "上記のシフト表作成後、必ずこの見出しと以下の形式で従業員ごとの合計勤務時間と試算月収を算出したMarkdown表を続けて出力してください。試算月収は「合計勤務時間 * 時給」で計算してください。\n"
    prompt += "従業員名 | 合計勤務時間 (h) | 試算月収 (円)\n"
    prompt += "--- | --- | ---\n"
    
    return prompt

# --- 業務要件の入力/編集フォーム ---
def job_requirement_form_component(key_suffix, existing_job_name=None, existing_data=None):
    """業務要件の入力/編集フォームを生成する"""
    
    is_editing = existing_data is not None
    form_title = f"業務要件「{existing_job_name}」を編集" if is_editing else "新しい業務要件を追加"
    submit_label = "変更を保存" if is_editing else "この業務要件を追加"
    
    default_data = {
        "job_name": existing_job_name if is_editing else "",
        "min_people": existing_data.get("min_people", 1) if is_editing else 1,
        "start_time": time.fromisoformat(existing_data["start_time"]) if is_editing else time(9, 0),
        "end_time": time.fromisoformat(existing_data["end_time"]) if is_editing else time(17, 0),
    }

    with st.form(key=f'job_req_form_{key_suffix}'):
        st.markdown(f"### {form_title}")
        
        job_name_input = st.text_input("業務名", value=default_data['job_name'], disabled=is_editing)
        
        min_people = st.slider("最低必要人数", min_value=1, max_value=5, value=default_data['min_people'], step=1, key=f"min_people_{key_suffix}")
        
        st.markdown("#### 必須時間帯")
        col_start, col_end = st.columns(2)
        with col_start:
            start_time = st.time_input("開始時刻", value=default_data['start_time'], step=60*15, key=f"job_start_time_{key_suffix}")
        with col_end:
            end_time = st.time_input("終了時刻", value=default_data['end_time'], step=60*15, key=f"job_end_time_{key_suffix}")
            
        add_job_button = st.form_submit_button(label=submit_label)

    # フォーム処理ロジック
    final_job_name = existing_job_name if is_editing else job_name_input
    
    if add_job_button and final_job_name:
        if start_time >= end_time:
            st.error("開始時刻は終了時刻より前に設定してください。")
        elif not is_editing and final_job_name in st.session_state.job_requirements:
            st.error(f"業務「{final_job_name}」はすでに登録されています。業務名を変更してください。")
        else:
            new_req = {
                'min_people': min_people, 
                'start_time': start_time.strftime('%H:%M'), 
                'end_time': end_time.strftime('%H:%M')
            }
            
            st.session_state.job_requirements[final_job_name] = new_req
            
            if is_editing:
                st.success(f"業務「{final_job_name}」の要件を更新しました。", icon="✅")
            else:
                st.success(f"業務「{final_job_name}」を追加しました。", icon="✅")
            
            # st.session_state.selected_job_for_action = "[新しく追加する]" を削除
            st.rerun()

    return add_job_button


# --- 従業員入力/編集フォーム ---
def employee_form_component(key_suffix, existing_data=None, index_to_update=None):
    """従業員データの入力/編集フォームを生成する"""
    
    is_editing = existing_data is not None
    form_title = "従業員データを編集" if is_editing else "新しい従業員を追加"
    submit_label = "変更を保存" if is_editing else "この従業員を追加"
    
    default_data = {
        "name": existing_data.get("name", "") if is_editing else "",
        "hourly_wage": existing_data.get("hourly_wage", 1200) if is_editing else 1200,
        "rest_time_hours": existing_data.get("rest_time_hours", 1.0) if is_editing else 1.0,
        "desired_monthly_income": existing_data.get("desired_monthly_income", 0) if is_editing else 0,
        "available_days": existing_data.get("available_days", ['月', '火', '水', '木', '金']) if is_editing else ['月', '火', '水', '木', '金'],
        "start_time": existing_data.get("start_time", time(9, 0)) if is_editing else time(9, 0),
        "end_time": existing_data.get("end_time", time(17, 0)) if is_editing else time(17, 0),
        "tasks": existing_data.get("tasks", []) if is_editing else [],
        "unavailable_dates_input": existing_data.get("unavailable_dates_input", "") if is_editing else "",
    }

    is_name_disabled = is_editing
    
    with st.form(key=f'employee_form_{key_suffix}'):
        st.markdown(f"### {form_title}")
        
        employee_name = st.text_input("名前", value=default_data['name'], disabled=is_name_disabled)

        st.markdown("### 💰 勤務条件と収入")
        col3, col4, col5 = st.columns(3)
        with col3:
            hourly_wage = st.number_input("時給 (円)", min_value=0, step=10, value=default_data['hourly_wage'], key=f"wage_{key_suffix}")
        with col4:
            rest_time_hours = st.number_input("休憩時間 (時間)", min_value=0.0, max_value=3.0, step=0.25, value=default_data['rest_time_hours'], format="%.2f", key=f"rest_{key_suffix}")
        with col5:
            desired_income = st.number_input("目標月収 (円) (任意)", min_value=0, step=10000, value=default_data['desired_monthly_income'], key=f"income_{key_suffix}")

        st.markdown("### ⏰ 勤務の制約")
        available_days = st.multiselect("入れる曜日", ['月', '火', '水', '木', '金', '土', '日'], default=default_data['available_days'], key=f"days_{key_suffix}")
        col1, col2 = st.columns(2)
        with col1:
            start_time = st.time_input("開始可能時間", value=default_data['start_time'], key=f"start_{key_suffix}")
        with col2:
            end_time = st.time_input("終了可能時間", value=default_data['end_time'], key=f"end_{key_suffix}")

        available_tasks = list(st.session_state.job_requirements.keys()) if st.session_state.job_requirements else ["レジ", "品出し", "その他"]
        st.markdown("### 🛠️ 担当可能業務")
        tasks = st.multiselect("担当できる業務 (複数選択可)", available_tasks, default=default_data['tasks'], key=f"tasks_{key_suffix}")

        st.markdown("### 🚫 入れない特定の日付")
        unavailable_dates_input = st.text_area("入れない日付 (YYYY-MM-DD 改行区切り)", value=default_data['unavailable_dates_input'], placeholder="例:\n2025-12-24", key=f"dates_{key_suffix}")

        submit_button = st.form_submit_button(label=submit_label)

    if submit_button and employee_name:
        unavailable_dates = []
        date_error = False
        for line in unavailable_dates_input.split('\n'):
            line = line.strip()
            if line:
                try:
                    unavailable_dates.append(date.fromisoformat(line))
                except ValueError:
                    st.error(f"日付の形式が不正です: {line}")
                    date_error = True
                    break
        
        if date_error:
            return 

        new_employee = Employee(
            name=employee_name, available_days=available_days, start_time=start_time, end_time=end_time,
            hourly_wage=hourly_wage, rest_time_hours=rest_time_hours, unavailable_dates=unavailable_dates,
            desired_monthly_income=desired_income, tasks=tasks
        )

        if is_editing and index_to_update is not None:
            st.session_state.employees[index_to_update] = new_employee
            st.success(f"従業員 **{employee_name}** のデータを更新しました！", icon="✅")
        else:
            st.session_state.employees.append(new_employee)
            st.success(f"従業員 **{employee_name}** のデータを追加しました！ (合計 {len(st.session_state.employees)} 人)", icon="✅")
        
        # st.session_state.selected_employee_for_action = "[新しく追加する]" を削除
        st.rerun() 
    
    return submit_button

# --- Streamlit アプリ本体 ---
def main():
    st.set_page_config(layout="wide")
    st.title("🗓️ Gemini AI シフト作成アプリ")

    # セッションステートの初期化
    if 'job_requirements' not in st.session_state:
        st.session_state.job_requirements = {}
    if 'employees' not in st.session_state:
        st.session_state.employees = []
    if 'shift_table' not in st.session_state:
        st.session_state.shift_table = ""
    # 選択肢のセッションステート
    if 'selected_employee_for_action' not in st.session_state:
        st.session_state.selected_employee_for_action = "[新しく追加する]" 
    if 'selected_job_for_action' not in st.session_state:
        st.session_state.selected_job_for_action = "[新しく追加する]" 

    # 1. 業務要件の設定

    st.header("1. 日々の業務要件を設定")
    
    job_names = list(st.session_state.job_requirements.keys())
    selection_options = ["[新しく追加する]"]+ job_names
    
    # 選択肢のウィジェット
    # これがインスタンス化された後、その値を直接変更するとエラーになる
    selected_job_action = st.selectbox(
        "編集する業務要件を選択、または新しく追加",
        options=selection_options,
        key="selected_job_for_action"
    )

    st.markdown("---")
    
    # 業務要件 フォーム表示のロジック
    
    if selected_job_action in job_names:
        # 編集モード
        job_name_to_edit = selected_job_action
        job_data_to_edit = st.session_state.job_requirements[job_name_to_edit]
        
        st.subheader(f"🛠️ {job_name_to_edit} の要件を編集")

        # 編集フォームを表示
        job_requirement_form_component(
            key_suffix="edit_job", 
            existing_job_name=job_name_to_edit,
            existing_data=job_data_to_edit,
        )
        
        # 業務要件削除ボタン
        if st.button(f"「{job_name_to_edit}」を削除", key="delete_job_button_form"):
            del st.session_state.job_requirements[job_name_to_edit]
            st.success(f"業務要件「{job_name_to_edit}」を削除しました。", icon="🗑️")
            # 削除処理は即座に反映されるべきなので、ここでリセット
            st.session_state.selected_job_for_action = "[新しく追加する]" 
            st.rerun()

    elif selected_job_action == "[新しく追加する]":
        # 新規追加モード
        st.subheader("🛠️ 新しい業務要件データを入力")
        job_requirement_form_component(key_suffix="add_job")
    
    # 業務要件 リストの表示

    if st.session_state.job_requirements:
        job_display_data = []
        for job, req in st.session_state.job_requirements.items():
            job_display_data.append({
                "業務名": job,
                "最低人数": req['min_people'],
                "必須時間帯": f"{req['start_time']} 〜 {req['end_time']}"
            })
        st.subheader(f"✅ 登録済みの業務要件一覧 ({len(st.session_state.job_requirements)} 種類)")
        df_jobs = pd.DataFrame(job_display_data)
        st.dataframe(df_jobs, hide_index=True, use_container_width=True)

    
    st.markdown("---")

    # 2. 従業員データの入力・編集

    st.header("2. 従業員データの入力・編集")
    
    employee_names = [emp.name for emp in st.session_state.employees]
    
    # リストに「新しく追加する」オプションを追加
    selection_options = ["[新しく追加する]"] + employee_names
    
    # 選択肢のウィジェット
    selected_employee_action = st.selectbox(
        "編集する従業員を選択、または新しく追加",
        options=selection_options,
        key="selected_employee_for_action"
    )

    st.markdown("---")

    # 従業員 フォーム表示のロジック

    if selected_employee_action in employee_names:
        # 編集モード
        index_to_edit = employee_names.index(selected_employee_action)
        employee_to_edit = st.session_state.employees[index_to_edit]
        
        st.subheader(f"👤 {selected_employee_action} のデータを編集")

        # 編集フォームを表示
        employee_form_component(
            key_suffix="edit_emp", 
            existing_data=employee_to_edit.to_dict(), 
            index_to_update=index_to_edit
        )
        
        # 従業員削除ボタン
        if st.button(f"「{selected_employee_action}」を完全に削除", key="delete_employee_button_form"):
            del st.session_state.employees[index_to_edit]
            st.success(f"従業員「{selected_employee_action}」を削除しました。", icon="🗑️")
            # 削除処理は即座に反映されるべきなので、ここでリセット
            st.session_state.selected_employee_for_action = "[新しく追加する]" 
            st.rerun()

    elif selected_employee_action == "[新しく追加する]":
        # 新規追加モード
        st.subheader("👤 新しい従業員データを入力")
        employee_form_component(key_suffix="add_emp")
    
    # 従業員リストの表示

    if st.session_state.employees:
        employee_data = []
        for emp in st.session_state.employees:
            time_diff = pd.to_datetime(str(emp.end_time)) - pd.to_datetime(str(emp.start_time))
            work_hours = time_diff.total_seconds() / 3600
            actual_work_hours = work_hours - emp.rest_time_hours
            
            income_display = f"{emp.desired_monthly_income:,}円" if emp.desired_monthly_income > 0 else "設定なし"
            
            employee_data.append({
                "名前": emp.name, "時給": f"{emp.hourly_wage:,}円", "休憩": f"{emp.rest_time_hours}h",
                "目標月収": income_display, "実働時間 (最大)": f"{actual_work_hours:.2f}h",
                "入れる曜日": ", ".join(emp.available_days),
                "時間帯": f"{emp.start_time.strftime('%H:%M')}〜{emp.end_time.strftime('%H:%M')}",
                "業務": ", ".join(emp.tasks), "入れない日": f"{len(emp.unavailable_dates)}日"
            })
        
        st.subheader(f"✅ 登録済みの従業員一覧 ({len(st.session_state.employees)} 人)")
        st.dataframe(pd.DataFrame(employee_data), use_container_width=True)

    
    st.markdown("---")


    # 3. シフト表の作成

    st.header("3. AIによるシフト表作成")

    col_date, col_button = st.columns([0.7, 0.3])
    with col_date:
        today = date.today()
        default_start = today.replace(day=1) + timedelta(days=32)
        default_start = default_start.replace(day=1)
        
        shift_period_start = st.date_input(
            "シフト作成開始日",
            value=default_start,
            key="shift_start_date"
        )
        
        _, last_day = calendar.monthrange(shift_period_start.year, shift_period_start.month)
        shift_period_end = shift_period_start.replace(day=last_day)
        st.info(f"シフト作成期間: **{shift_period_start.strftime('%Y/%m/%d')}** から **{shift_period_end.strftime('%Y/%m/%d')}** まで")


    if len(st.session_state.employees) == 0 or len(st.session_state.job_requirements) == 0:
        st.warning("業務要件と従業員データを両方入力してから、シフトを作成してください。")
    elif 'GEMINI_API_KEY' not in os.environ and 'GOOGLE_API_KEY' not in os.environ:
        st.error("環境変数に `GEMINI_API_KEY` または `GOOGLE_API_KEY` が設定されていません。APIキーを設定してください。")
    else:
        with col_button:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🤖 AIシフト表を作成する", type="primary"):
                prompt = create_shift_prompt(
                    st.session_state.employees, 
                    st.session_state.job_requirements,
                    shift_period_start,
                    shift_period_end
                )
                
                with st.spinner("Gemini AIが最適なシフト表を作成中です..."):
                    try:
                        client = genai.Client()
                        response = client.models.generate_content(
                            model='gemini-2.5-flash',
                            contents=prompt
                        )
                        st.session_state.shift_table = response.text
                        st.success("シフト表の作成が完了しました！")
                        
                    except APIError as e:
                        st.error(f"GemINI APIエラー: APIキーまたはリクエストに問題があります。詳細: {e}")
                    except Exception as e:
                        st.error(f"予期せぬエラーが発生しました: {e}")

    # 4. 結果の表示
    
    st.markdown("---")
    st.header("最終シフト表")
    if st.session_state.shift_table:
        separator = "# 💰 従業員別 勤務と収入サマリー"
        
        if separator in st.session_state.shift_table:
            shift_table_part, summary_part = st.session_state.shift_table.split(separator, 1)
            
            st.subheader("シフト詳細")
            st.markdown(shift_table_part.strip())
            
            st.markdown("---")
            
            st.subheader("📊 試算月収サマリー")
            st.info("AIがシフト表に基づいて計算した、従業員ごとの合計勤務時間と試算月収です。")
            st.markdown(separator)
            st.markdown(summary_part.strip())
        else:
            st.subheader("シフト詳細")
            st.markdown(st.session_state.shift_table)
            st.warning("AIの応答に試算月収サマリーのテーブルが見つかりませんでした。再度AIシフト表作成を試すか、プロンプトの指示を確認してください。")
    else:
        st.info("シフト表がまだ作成されていません。")

if __name__ == "__main__":
    main()