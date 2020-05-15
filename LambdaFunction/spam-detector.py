import json
import boto3
import re
import os
from datetime import datetime
import dateutil
from sms_spam_classifier_utilities import one_hot_encode
from sms_spam_classifier_utilities import vectorize_sequences

vocabulary_length = 9013;
input_date_format = '%a, %d %b %Y %H:%M:%S %z';
output_date_format = '%m-%d-%Y %H:%M:%S %Z %z';
EST = dateutil.tz.gettz('US/Eastern');

sagemaker_endpoint = os.environ['ENDPOINT_NAME'];

def invoke_prediction(mail_body):
    mail_body = mail_body.replace('\r\n', ' ').replace('\r', ' ').replace('\n', ' ');
    mail_body = [mail_body];
    # print(mail_body)
    runtime= boto3.client('runtime.sagemaker');
    one_hot_test_messages = one_hot_encode(mail_body, vocabulary_length);
    encoded_test_messages = vectorize_sequences(one_hot_test_messages, vocabulary_length);
    msg = json.dumps(encoded_test_messages.tolist());
    response = runtime.invoke_endpoint(EndpointName=sagemaker_endpoint,ContentType='application/json', Body=msg);
    # print(response)
    result = response['Body'];
    res = json.loads(result.read().decode("utf-8"));
    # print(res)
    predicted_score = int(res['predicted_label'][0][0]);
    predicted_probability = float(res['predicted_probability'][0][0]);
    predicted_label = 'Spam' if predicted_score == 1 else 'Ham';
    predicted_probability = predicted_probability if predicted_score == 1 else (1 - predicted_probability);
    print("Predicted Label = %s ; Prediction Confidence = %.2f" % (predicted_label, predicted_probability));
    return predicted_label, predicted_probability; 

def send_response_email(send_date_converted, sender_email, subject, mail_body, prediction, score):
    score = score * 100;
    response_mail = "We received your email sent at %s with the subject \"%s\".\n\nHere is a 240 character sample of the email body:\n\n%s\n\nThe email was categorized as %s with a %.2f%% confidence." % (send_date_converted, subject, mail_body[0:240], prediction, score);
    # print("Sending [%s] mail to [%s]" % (response_mail, sender_email));
    client = boto3.client('ses');
    response = client.send_email(Source='test@wtf.engineer', 
        Destination={'ToAddresses': [sender_email], 'BccAddresses': ['nitinzmobile@gmail.com']},
        Message={
            'Subject': {
                'Data': subject,
                'Charset': 'utf-8'
            },
            'Body': {
                'Text': {
                    'Data': response_mail,
                    'Charset': 'utf-8'
                }
            }
        }
    );
    # print(response);

def clean_mail_body(body):
    mail_body_regex = re.compile(r"(Feedback-ID:|Content-Transfer-Encoding:|Content-Type: *text/plain) *[^\r\n]*(.+)", re.DOTALL);
    mail_body = re.search(mail_body_regex, body).group(2);
    check1 = re.search(r"^\s*Content-Transfer-Encoding: *[^\r\n]*(.+)", mail_body, re.DOTALL);
    if check1:
        mail_body = check1.group(1);
    check2 = re.search(r"(.+)\r\n--[0-9a-zA-Z]+\r\nContent-Type:.*", mail_body, re.DOTALL);
    if check2:
        mail_body = check2.group(1);
    mail_body = mail_body.replace('=\r\n', '').replace('=E2=80=99', '\'').replace('\r\n\r\n', '\r\n').strip();
    return mail_body;

def process_mail(bucket, objectKey):
    client = boto3.client('s3');
    response = client.get_object(Bucket=bucket, Key=objectKey);
    # print(response)
    body = response['Body'].read();
    body = body.decode('utf8');
    # Extract date, subject, sender_email, 240 char body
    send_date = re.search('Date: (.*) *[\r\n]', body).group(1).strip();
    sender_email = re.search('From: (.*) *[\r\n]', body).group(1).strip();
    check1 = re.search('[^<]* *<(.*@.*)>', sender_email);
    if check1:
        sender_email = check1.group(1);
    subject = re.search('Subject: (.*) *[\r\n]', body).group(1).strip();
    send_date_converted = datetime.strptime(send_date, input_date_format).astimezone(EST).strftime(output_date_format);
    # print("Date = %s ; Sender = %s ; Subject = %s" % (send_date_converted, sender_email, subject));
    mail_body = clean_mail_body(body);
    return send_date_converted, sender_email, subject, mail_body;

def lambda_handler(event, context):
    bucket = event['Records'][0]['s3']['bucket']['name'];
    key = event['Records'][0]['s3']['object']['key'];
    send_date_converted, sender_email, subject, mail_body = process_mail(bucket, key);
    prediction, score = invoke_prediction(mail_body);
    response = send_response_email(send_date_converted, sender_email, subject, mail_body, prediction, score);
    # print("Bucket = %s ; ObjectKey = %s" % (bucket, key));
    return {
        'statusCode': 200,
        'body': json.dumps('Mail successfully sent')
    }
