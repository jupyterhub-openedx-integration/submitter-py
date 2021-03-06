import argparse
import socket
import requests
import hashlib
import traceback
import yaml
import json

'''
config.yaml

singleuser:
  lifecycleHooks:
    postStart:
      exec:
        command:
          - sh
          - "-c"
          - >
            cd /home/jovyan
            # consider extending the pythonpath in the python magic code, that would be clean.
            # todo, use fileset  in the makefile to inject the magic code into ~/.ipython/startup/...
            
            wget https://some.real.url/submitter.py
            SUBMIT_SERVER_USERID="staff" 
            SUBMIT_SERVER_PASSWD="@staff needs add passwd here."
            python3 submitter.py --submit-passwd $SUBMIT_SERVER_PASSWD
'''

def parse_args():
    parser = argparse.ArgumentParser(description=(
        'program that submits answers to the submission server.'
        'there are two modes of operation. '
        'PodStarting, and SubmitAnswer'
    ))

    anon_id_help_msg = (
        "This should be the anonymous id generated by edx for each student. "
        "or something close to it, there may need to be some munging to get it right"
    )
    
    parser.add_argument('--edx-anon-id', dest='edx_anon_id', type=str,
                        help='edx anonymous id')
    parser.add_argument('--submit-passwd', dest='submit_passwd', type=str,
                        help="staff-only, password for submission server")
    
    args = parser.parse_args()
    return args

def check_pod_starting_mode(args):
    '''check to make sure all the flags necessary for pod starting mode are used.'''
    # if not args.edx_anon_id: 
    #     raise Exception("In pod starting mode, the program must be run with: --edx-anon-id=[todo figure out example here]")
     
    if not args.submit_passwd: 
        raise Exception("In pod starting mode, the program must be run with: --submit-passwd=[an actual password]")
    
    return True

class Mode:
    def get_edx_anon_id(self):
        '''jupyter hub assigns the hostname to the edx_anon_id passed in by
        the lti_launcher. TODO this might need to be cleaned up to
        make remoxblock happy
        '''
        return generate_jupyterhub_userid(socket.gethostname())
    
class SubmissionMode(Mode):
    def __init__(self, labname, answers_json):
        self.send_request(labname, answers_json)

    def send_request(self, labname, answers_json):        
        '''Sends a request to the submission server that this pod, with this
        ip address and this edx-anon-id is submitting answers,
        trusting that the submission server is going to be checking
        that the ip in this request is equal to what was logged
        earlier on the submission server.
        '''
        sess = requests.Session()
        req = requests.Request(
            url="http://submitter:3000/submit-answers", # there must be a k8s service called submitter.
            method="POST",
            data={
                "edx-anon-id": self.get_edx_anon_id(),
                "labname": labname,
                "lab-answers": answers_json,
            },
            # This user/pass is intentional
            auth=("student", "student")
            # the submitter server is looking at the student's pod's
            # IP to make sure the answers are legit.
        )
        rsp = sess.send(req.prepare())
        print(rsp)
        
class _PodStartingMode(Mode):
    ''' please do not import this class '''
    
    def __init__(self):
        print("pod starting mode")
        self.cmdline_args = parse_args()
        self.send_request()
        
    def send_request(self):        
        '''Sends a request to the submission server, that this pod, with this
        ip address and this edx-anon-id is starting.

        '''
        sess = requests.Session()
        
        req = requests.Request(
            url="http://submitter:3000/pod-starting", # ensure a k8s service called submitter exists.
            method="POST",
            data={
                "edx-anon-id": self.get_edx_anon_id(),                
            },
            auth=("staff", self.cmdline_args.submit_passwd)
        )
        rsp = sess.send(req.prepare())
        print(self.get_edx_anon_id())
        print(rsp.text)


def generate_jupyterhub_userid(anonymous_student_id):
    # TODO make sure anonymous_student_id starts with "jupyter-"
    anon_id = anonymous_student_id

    # jupyterhub truncates this and appends a five character hash.
    # https://tljh.jupyter.org/en/latest/topic/security.html
    #
    # where is this done?
    # https://gist.github.com/martinclaus/c6f229de82769b0b4ae6c7bf3b232106
    # https://github.com/jupyterhub/the-littlest-jupyterhub/blob/main/tljh/normalize.py

    userhash = hashlib.sha256(anon_id.encode("utf-8")).hexdigest()
    return f"{anon_id[:26]}-{userhash[:5]}"

def env_lookup(env, varname):
    if varname in env:
        return env[varname]
    return None



def jsonerr(msg):
    return json.dumps({ok: False, error: msg})
 
def submit_from_js(lab_name, local_env):
    try:
        # labconfig.yaml is located in the notebook directory.
        config = yaml.load(open("labconfig.yaml"), Loader=yaml.CLoader)
        if not lab_name in config["Labs"]:
            return jsonerr((f"Couldn't find lab: {lab_name} in the labconfig.yaml, ",
                            "please make sure it is the same name as this notebook name")) 
        
        vars = config["Labs"][lab_name].keys()
        answers = {}
        
        for v in vars:
            answers[v] = env_lookup(local_env, v)

        json_answers = json.dumps(answers)
        SubmissionMode(lab_name, json_answers)
        return json_answers
    
    except Exception as e:
        return traceback.format_exc()

 
if __name__ == "__main__":
    # in PodStartingMode.
    # TODO ensure the submitter service is running!
    _PodStartingMode()
