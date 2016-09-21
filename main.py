# -*- coding: utf-8 -*-

from flask import Flask, render_template, request, redirect, url_for
from flask import escape, Markup
from wtforms import Form, TextAreaField, StringField, validators, ValidationError
from pytz import timezone, utc
from google.appengine.ext import ndb
from flask_wtf.file import FileField
from werkzeug.utils import secure_filename
from werkzeug.datastructures import CombinedMultiDict
import cloudstorage as gcs
import uuid, tempfile, os
from google.appengine.api.app_identity import get_default_gcs_bucket_name

app = Flask(__name__)
bucket_name = os.environ.get('BUCKET_NAME', get_default_gcs_bucket_name())
storage_path = 'https://storage.cloud.google.com/%s' % bucket_name

class Message(ndb.Model):
    timestamp = ndb.DateTimeProperty(auto_now_add=True)
    name = ndb.StringProperty(required=True)
    message = ndb.StringProperty(required=True)
    filename = ndb.StringProperty(required=False)

    @classmethod
    def last_messages(cls):
        return cls.query().order(-cls.timestamp)

@app.template_filter('add_br')
def linesep_to_br_filter(s):
    return escape(s).replace('\n', Markup('<br>'))

@app.template_filter('local_tz')
def local_tz_filter(timestamp):
    jst = timezone('Asia/Tokyo')
    jst_timestamp = utc.localize(timestamp).astimezone(jst)
    return jst_timestamp.strftime("%Y/%m/%d %H:%M:%S")

def is_image():
    def _is_image(form, field):
        extensions = ['jpg', 'jpeg', 'png', 'gif']
        if field.data and \
           field.data.filename.split('.')[-1] not in extensions:
            raise ValidationError()
    return _is_image

class MessageForm(Form):
    input_name = StringField(u'お名前', [validators.Length(min=1, max=16)])
    input_message = TextAreaField(u'メッセージ',
                                  [validators.Length(min=1, max=1024)])
    input_photo = FileField(u'画像添付(jpg, jpeg, png, gif)',
                            validators=[is_image()])

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/messages')
def messages():
    form = MessageForm(request.form)
    last_messages = Message.last_messages().fetch(5)
    last_messages = [message for message in last_messages]
    last_messages.reverse()
    return render_template('messages.html', storage_path=storage_path,
                           form=form, messages=last_messages)

@app.route('/post', methods=['POST'])
def post():
    form = MessageForm(CombinedMultiDict((request.files, request.form)))
    if request.method == 'POST' and form.validate():
        name = request.form['input_name']
        message = request.form['input_message']
        if form.input_photo.data.filename:
            filename = '%s.%s' % (str(uuid.uuid4()),
                                  secure_filename(form.input_photo.data.filename))
            content_types = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
                             'png': 'image/png', 'gif': 'image/gif'}
            content_type = content_types[filename.split('.')[-1]]
            write_retry_params = gcs.RetryParams(backoff_factor=1.1)
            gcs_file = gcs.open('/%s/%s' % (bucket_name, filename), 'w',
                                retry_params=write_retry_params,
                                content_type=content_type,
                                options={'x-goog-acl': 'public-read'})
            for _ in form.input_photo.data.stream:
                gcs_file.write(_)
            gcs_file.close()
            entry = Message(name=name, message=message, filename=filename)
        else:
            entry = Message(name=name, message=message, filename=None)
        entry.put()
        return render_template('post.html', name=name, timestamp=entry.timestamp)
    else:
        return redirect(url_for('messages'))
