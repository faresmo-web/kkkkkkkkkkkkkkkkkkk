from flask import Flask, render_template, Response, request, send_from_directory, abort, jsonify
import config
import time
import hashlib
import subprocess
import os
import shutil
from urllib.parse import quote

app = Flask(__name__)

SECRET_KEY = "HexSports_Super_Secret_Key_2026"
CACHE_DIR = "stream_cache"

# إعادة إنشاء المجلد المؤقت عند تشغيل السيرفر
if os.path.exists(CACHE_DIR):
    shutil.rmtree(CACHE_DIR)
os.makedirs(CACHE_DIR)

def generate_secure_token(user_ip):
    expiration = int(time.time()) + 7200  
    raw_string = f"{expiration}-{SECRET_KEY}"
    return f"{hashlib.sha256(raw_string.encode()).hexdigest()}_{expiration}"

def verify_token(user_ip, token):
    try:
        token_hash, expiration = token.split('_')
        if int(time.time()) > int(expiration):
            return False
        raw_string = f"{expiration}-{SECRET_KEY}"
        return token_hash == hashlib.sha256(raw_string.encode()).hexdigest()
    except:
        return False

# تشغيل FFmpeg في الخلفية مع تضبيط الـ Keyframes لمنع "الرجعة الخفيفة"
ffmpeg_cmd = [
    'ffmpeg',
    '-headers', f"Referer: {config.REFERER}\r\nUser-Agent: {config.USER_AGENT}\r\n",
    '-i', config.STREAM_URL,
    '-i', 'logo.png',
    '-filter_complex', '[1:v]colorkey=0x00B050:0.3:0.1,scale=155:-1[logo];[0:v][logo]overlay=main_w-overlay_w-15:23',
    '-c:v', 'libx264',
    '-b:v', '2500k',
    '-maxrate', '2800k',
    '-bufsize', '5000k',
    '-preset', 'ultrafast',        # استخدام ultrafast لتقليل استهلاك المعالج وسرعة إنتاج القطع
    '-tune', 'zerolatency',   
    '-g', '50',                    # تحديد Keyframe كل ثانيتين (GOP) ليتطابق مع hls_time
    '-sc_threshold', '0',          # إلغاء كشف تغير المشاهد لتفادي تفاوت حجم القطع
    '-c:a', 'copy',           
    '-f', 'hls',
    '-hls_time', '2',         
    '-hls_list_size', '4',
    '-hls_flags', 'delete_segments',
    os.path.join(CACHE_DIR, 'live.m3u8')
]

# تشغيل البث تلقائياً مع السيرفر
ffmpeg_process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# 1. الصفحة الرئيسية (جدول المباريات)
@app.route('/')
def index():
    return render_template('index.html')

# 2. صفحة الـ Player المنفصلة لبوابة العرض
@app.route('/watch')
def watch():
    user_ip = request.remote_addr
    user_token = generate_secure_token(user_ip)
    
    # استقبال رابط السيرفر المحدد من الـ URL
    stream_url = request.args.get('stream')
    if not stream_url:
        # إيلا ما كانش سيرفر محدد، كنخدمو بالبث المحلي التلقائي
        stream_url = f"/live.m3u8?token={user_token}"
        
    return render_template('player.html', token=user_token, stream_url=stream_url)

# 3. صفحة تحميل تطبيق الـ APK
@app.route('/download')
def download():
    return render_template('download.html')

# دالة لتمرير ملف الدليل m3u8 محمي بالتوكن
@app.route('/live.m3u8')
def proxy_m3u8():
    user_ip = request.remote_addr
    token = request.args.get('token')
    
    if not token or not verify_token(user_ip, token):
        abort(403)
        
    try:
        file_path = os.path.join(CACHE_DIR, 'live.m3u8')
        
        if not os.path.exists(file_path):
            print(f"❌ Error: {file_path} does not exist yet! FFmpeg might be slow or failed.")
            return "جاري تجهيز البث... أعد المحاولة بعد ثوانٍ", 503
            
        with open(file_path, 'r') as f:
            content = f.read()
        
        # تعديل محتوى الملف ليمر عبر البايثون مع التوكن
        new_content = []
        for line in content.splitlines():
            if line.endswith('.ts'):
                new_content.append(f"{line}?token={token}")
            else:
                new_content.append(line)
                
        response = Response('\n'.join(new_content), content_type='application/x-mpegURL')
        return response
    except Exception as e:
        print(f"❌ Error reading m3u8: {str(e)}")
        return "خطأ في قراءة ملف البث", 500

# دالة لتوزيع قطع الـ TS وحمايتها بالتوكن (حل مشكل الـ 404)
@app.route('/<filename>.ts')
def proxy_ts(filename):
    user_ip = request.remote_addr
    token = request.args.get('token')
    
    if not token or not verify_token(user_ip, token):
        abort(403)
        
    return send_from_directory(CACHE_DIR, f"{filename}.ts")

@app.route('/check-update', methods=['GET'])
def check_update():
    return jsonify({
        "latest_version": "2.0.0"
    })

# الـ API الخاص بجدول المباريات مع توجيه الروابط نحو صفحة الـ Player (/watch)
@app.route('/matches', methods=['GET'])
def get_matches():
    user_ip = request.remote_addr
    user_token = generate_secure_token(user_ip)
    
    # البث المحلي المحمي بالتوكن
    local_stream_1080p = f"/live.m3u8?token={user_token}"
    local_stream_720p = f"/live.m3u8?token={user_token}"
    
    return jsonify([
        {
            "title": "كأس العالم",
            "team1": "إسبانيا",
            "team1_logo": "https://imgs.ysscores.com/teams/128/6231763087210.png",
            "team2": "فرنسا",
            "team2_logo": "https://imgs.ysscores.com/teams/128/2961763078000.png",
            "time": "شغال الآن",
            
            # URL-encode the stream path so the inner ?token= doesn't break /watch?stream=
            "servers": [
                {"name": "سيرفر 1 - جودة عالية 1080p", "url": f"/watch?stream={quote(local_stream_1080p, safe='')}"},
                {"name": "سيرفر 2 - جودة متوسطة 720p", "url": f"/watch?stream={quote(local_stream_720p, safe='')}"},
                {"name": "سيرفر 3 - احتياطي خارجي", "url": f"/watch?stream={quote('https://buzcdn.com/live/master.m3u8', safe='')}"}
            ]
        }
    ])
@app.route('/download-apk')
def download_apk():
    try:
        # هاد الدالة كاتمشي للمجلد الرئيسي وتصيفط ملف الـ APK نيتيف للمتصفح
        return send_from_directory(os.getcwd(), 'app-release.apk', as_attachment=True)
    except Exception as e:
        # إيلا كان اسم الملف مبدل أو ما كاينش غاتعلمك فـ الـ CMD
        print(f"❌ Error downloading APK: {str(e)}")
        return "الملف غير موجود فـ السيرفر، تأكد من الاسم الحقيقي للـ APK", 404

if __name__ == '__main__':
    try:
        app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
    finally:
        ffmpeg_process.kill()  # إغلاق FFmpeg عند إطفاء السيرفر