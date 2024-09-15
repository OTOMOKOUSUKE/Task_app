from flask import Flask
from flask import render_template , request ,redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import case
import sqlite3
from flask_login import UserMixin,LoginManager,login_user,logout_user,login_required,current_user

from werkzeug.security import generate_password_hash,check_password_hash
import os

from datetime import datetime, timedelta
import pytz
from sqlalchemy.orm import Mapped, mapped_column, relationship

JST = pytz.timezone('Asia/Tokyo')

app = Flask(__name__)
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///task.db'
app.config['SECRET_KEY'] = os.urandom(24)
db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


def current_jst_time():
    return datetime.now(JST)

class Task(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    taskname: Mapped[str] = mapped_column(db.String(100), nullable=False)  # タスクの名前（日本語対応）
    body: Mapped[str] = mapped_column(db.String(100), nullable=True)
    deadline: Mapped[datetime] = mapped_column(db.DateTime, nullable=False)  # 期限
    priority: Mapped[str] = mapped_column(db.String(100), nullable=False)  # 優先度
    progress: Mapped[int] = mapped_column(db.Integer, nullable=False, default=0)  # 進捗（0から100の範囲）
    user_id: Mapped[int] = mapped_column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    user = relationship('User', back_populates='tasks')

class User(UserMixin, db.Model):
    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(db.String(18), unique=True, nullable=False) #ユーザーネーム
    password: Mapped[str] = mapped_column(db.String(12), nullable=False) #パスワード
    nickname: Mapped[str] = mapped_column(db.String(12), nullable=False) #ニックネーム
    tasks_completed_today: Mapped[int] = mapped_column(db.Integer, nullable=False, default=0)
    tasks_completed_this_week: Mapped[int] = mapped_column(db.Integer, nullable=False, default=0)
    last_reset_date: Mapped[datetime] = mapped_column(db.DateTime, nullable=False, default=current_jst_time)

    def reset_counters(self):
        # 日本時間での現在の日付を取得
        today = datetime.now(JST).date()

        # last_reset_dateがNoneの場合の対策
        if self.last_reset_date is None or self.last_reset_date.astimezone(JST).date() < today:
            self.tasks_completed_today = 0
            
            # 今週の月曜日の日付を計算
            week_start = today - timedelta(days=today.weekday())
            
            # 今週の始まりより前であれば、週のカウントもリセット
            if self.last_reset_date is None or self.last_reset_date.astimezone(JST).date() < week_start:
                self.tasks_completed_this_week = 0
            
            # リセット日を日本時間で更新
            self.last_reset_date = datetime.now(JST)

    def complete_task(self):
        self.reset_counters()  # 必要に応じてカウンターをリセット
        #self.tasks_completed_today += 1
        #self.tasks_completed_this_week += 1
        db.session.commit()

    tasks = relationship('Task', back_populates='user')

class Request(db.Model):
    id: Mapped[int] = mapped_column(db.Integer, primary_key=True, autoincrement=True)
    requester_id: Mapped[str] = mapped_column(db.String(18), db.ForeignKey('user.username'), nullable=False)
    target_user_id: Mapped[str] = mapped_column(db.String(12), db.ForeignKey('user.username'), nullable=False)
    status: Mapped[str] = mapped_column(db.String(20), nullable=False, default='保留')
    timestamp: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.utcnow, nullable=False)

    requester = db.relationship('User', foreign_keys=[requester_id], backref='sent_requests')
    target_user = db.relationship('User', foreign_keys=[target_user_id], backref='received_requests')


#with app.app_context():
    #db.drop_all()
    #db.create_all()






@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.route('/',methods=['GET','POST'])
def home():
    if request.method == 'GET':
        return render_template('home.html')


@app.route('/mypage', methods=['GET', 'POST'])
@login_required
def index():
    if request.method == 'GET':
        priority_order = case(
            (Task.priority == 'High', 1),
            (Task.priority == 'Medium', 2),
            (Task.priority == 'Low', 3)
        )
        
        
        user = db.session.query(User).filter_by(id=current_user.id).first()
        # 現在のユーザーのタスクを取得
        tasks = Task.query.filter_by(user_id=current_user.id).order_by(priority_order, Task.deadline.asc()).all()
        
        # 承認した友人と承認された友人のリストを取得
        approved_by_me_requests = Request.query.filter_by(target_user_id=current_user.username, status='承認').all()
        approved_by_me_friends = [req.requester_id for req in approved_by_me_requests]
        
        approved_for_me_requests = Request.query.filter_by(requester_id=current_user.username, status='承認').all()
        approved_for_me_friends = [req.target_user_id for req in approved_for_me_requests]
        
        # 友人リストを重複排除して統合
        all_friends = list(set(approved_by_me_friends + approved_for_me_friends))
        
        # 友人のタスクを取得
        friend_user = None
        friend_tasks = {}
        for friend in all_friends:
            friend_user = User.query.filter_by(username=friend).first()
            
            if friend_user:
                friend_task = Task.query.filter_by(user_id=friend_user.id).order_by(priority_order, Task.deadline.asc()).first()
                
                if friend_task:
                    friend_tasks[friend] = friend_task
        print(friend_tasks)
        # テンプレートにデータを渡してレンダリング
        return render_template('mypage.html', tasks=tasks, user=user, friend_user=friend_user,  all_friends=all_friends, friend_tasks=friend_tasks, logginguser=current_user.username)


@app.route('/friend_tasks/<username>', methods=['GET'])
@login_required
def friend_tasks(username):
    # 友人のユーザーオブジェクトを取得
    friend_user = User.query.filter_by(username=username).first()
    
    if friend_user:
        # 友人のすべてのタスクを取得
        tasks = Task.query.filter_by(user_id=friend_user.id).order_by(
            case(
                (Task.priority == 'High', 1),
                (Task.priority == 'Medium', 2),
                (Task.priority == 'Low', 3)
            ),
            Task.deadline.asc()
        ).all()
        
        return render_template('friend_tasks.html', friend=friend_user, tasks=tasks, logginguser=current_user.username)
    else:
        flash("友人が見つかりませんでした", 'warning')
        return redirect(url_for('index'))


@app.route('/signup',methods=['GET','POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        password_check = request.form.get('password_check')
        nickname = request.form.get('nickname')
       # ユーザー名とパスワードの長さをチェック
        if len(username) < 8:
            flash('ユーザー名は8文字以上である必要があります。', 'warning')
            return redirect('/signup')
        if len(password) < 8:
            flash('パスワードは8文字以上である必要があります。', 'warning')
            return redirect('/signup')
        if password != password_check: #パスワードのダブルチェック
            flash('パスワードが違います。', 'warning')
            return redirect('/signup')

        # ユーザー名の重複チェック
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('そのユーザー名はすでに使用されています。別のユーザー名を選んでください。', 'warning')
            return redirect('/signup')

        user = User(username=username,nickname=nickname, password=generate_password_hash(password, method='pbkdf2:sha256'))

        db.session.add(user)
        db.session.commit()
        return redirect('/login')
    else:
        return render_template('signup.html')
    
@app.route('/login',methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect('/mypage')
        else:
            flash('パスワードもしくはユーザーネームが正しくありません。', 'warning')
            return render_template('login.html')
    else:
        return render_template('login.html')
    
@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect('/login')

@app.route('/nickname',methods=['GET','POST'])
@login_required
def nickname():
    user = db.session.query(User).filter_by(id=current_user.id).first()
    if request.method == 'GET':
        return render_template('nickname.html',user=user, logginguser=current_user.username)
    else:
        user.nickname = request.form.get('nickname')
        db.session.commit()
        return redirect('/mypage')

@app.route('/create',methods=['GET','POST'])
@login_required
def create():
    if request.method == 'POST':
        taskname = request.form.get('taskname')
        body = request.form.get('body')
        deadline_str = request.form.get('deadline')
        progress = request.form.get('progress')
        priority = request.form.get('priority')

       # 日本時間 (JST) に変換
        try:
            # 入力された日時文字列をdatetimeオブジェクトに変換
            deadline = datetime.strptime(deadline_str, '%Y-%m-%dT%H:%M')
            # タイムゾーンをJSTに設定
            tokyo_tz = pytz.timezone('Asia/Tokyo')
            deadline = tokyo_tz.localize(deadline)
        except ValueError:
            flash('無効な日付形式です。入力しなおしてください', 'warning')
            return redirect(url_for('create'))

        task = Task(taskname=taskname, body=body, deadline=deadline, progress=progress, priority=priority, user_id=current_user.id)


        db.session.add(task)
        db.session.commit()
        return redirect('/mypage')
    else:
        return render_template('create.html', logginguser=current_user.username)
    

@app.route('/<int:id>/update',methods=['GET','POST'])
@login_required
def update(id):
    task = Task.query.get(id)
    if request.method == 'GET':
        return render_template('update.html',task=task, logginguser=current_user.username)
    else:
        task.taskname = request.form.get('taskname')
        task.body = request.form.get('body')
        task.deadline_str = request.form.get('deadline')
        task.progress = request.form.get('progress')
        task.priority = request.form.get('priority')  # 優先度の更新



        # 日本時間 (JST) に変換
        try:
            # 入力された日時文字列をdatetimeオブジェクトに変換
            deadline = datetime.strptime(task.deadline_str, '%Y-%m-%dT%H:%M')
            # タイムゾーンをJSTに設定
            tokyo_tz = pytz.timezone('Asia/Tokyo')
            deadline = tokyo_tz.localize(deadline)
        except ValueError:
            flash('無効な日付形式です。入力しなおしてください', 'warning')
            return redirect(url_for('update'))
        
        db.session.commit()
        return redirect('/mypage')
    

@app.route('/<int:id>/delete',methods=['GET'])
@login_required
def delete(id):
    task = Task.query.get(id)
    
    db.session.delete(task)
    db.session.commit()
    return redirect('/mypage')

@app.route('/<int:id>/complete',methods=['GET'])
@login_required
def complete(id):
    task = Task.query.get(id)
    user = db.session.query(User).filter_by(id=current_user.id).first()
    user = user

    user.reset_counters()

    user.tasks_completed_today += 1
    user.tasks_completed_this_week += 1

    db.session.delete(task)
    db.session.commit()
    return redirect('/mypage')


@app.route('/send_request', methods=['GET', 'POST'])
@login_required
def send_request():
    if request.method == 'GET':
        return render_template('send_request.html', logginguser=current_user.username)
    else:
        target_username = request.form.get('username')  # リクエスト対象のユーザー名を取得
        
        target_user = User.query.filter_by(username=target_username).first()  
        # 対象ユーザーをデータベースから取得
        requester_user=current_user
        
        if target_user:
            if target_user!=current_user:
                # 新しいリクエストを作成
                new_request = Request(requester_id=requester_user.username, target_user_id=target_user.username)
                db.session.add(new_request)  # リクエストをデータベースに追加
                db.session.commit()  # 変更をコミット
                flash('リクエストが送信されました', 'success')
                return redirect('/send_request')
            elif target_user==current_user:
                flash('このユーザーはあなた自身です', 'warning')
                return redirect('/send_request')
        else:
            flash('ユーザーが見つかりませんでした', 'warning')
            return redirect('/send_request')








@app.route('/requests', methods=['GET','POST'])
@login_required
def handle_request():
    if request.method == 'GET':
        requests = Request.query.all()
        return render_template('requests.html', requests=requests, logginguser=current_user.username)
    else:
        request_id = request.form.get('request_id', type=int)
        req = Request.query.get_or_404(request_id)

        action = request.form.get('action')

        
        if action == 'approve':
            req.status = '承認'
            flash('承認しました。', 'success')  # 承認メッセージをフラッシュ
        elif action == 'deny':
            req.status = '拒否'
            flash('拒否しました。', 'success')  # 拒否メッセージをフラッシュ
    db.session.commit()
    return redirect(url_for('handle_request'))












