import getopt
import json
import sys

from cisco_sdwan_policy.ViptelaRest import ViptelaRest

main_templates={}
loaded_templates={}
policy_templates={}
uuid_pairs={}

def update_template(data):
    data["templateId"] = uuid_pairs[data["templateId"]]
    if data.get("subTemplates"):
        for sub_tmp in data["subTemplates"]:
            sub_tmp["templateId"] = uuid_pairs[sub_tmp["templateId"]]
    return data


def load_template(rest, data):
    result = rest.get_request("template/feature/object/{}".format(data["templateId"]))
    info = result.json()
    if data.get("subTemplates"):
        for sub_tmp in data["subTemplates"]:
            load_template(rest,sub_tmp)
    if not loaded_templates.get(data["templateId"]):
        loaded_templates[data['templateId']] = info
    # print(result.json())


def backup_template(server_info,template_name=None):

    # Load all policy in vManage
    rest = ViptelaRest.init(server_info)
    resp = rest.get_request("template/device")
    templates = resp.json()["data"]
    for template in templates:
        result = rest.get_request("template/device/object/{}".format(template["templateId"]))
        obj= result.json()
        if template_name:
            if obj["templateName"]!=template_name:
                continue
        if obj["configType"]=="template":
            for sub_template in obj["generalTemplates"]:
                load_template(rest,sub_template)
            if "policyId" in obj and obj["policyId"]!="":
                policy_id = obj["policyId"]
                # Currently we do not support feature local policies. Stay tuned for the support from cisco-sdwan-policy module. So if the template has a feature policy, just ignore this template.
                result_t = rest.get_request("template/policy/vedge/definition/{}".format(policy_id))
                result=result_t.json()
                if result["policyType"]=="feature":
                    # Don't support yet.
                    del obj["policyId"]
                else:
                    policy_templates[policy_id] = result
            if "securityPolicyId" in obj and obj["securityPolicyId"]!="":
                security_policy = obj["securityPolicyId"]
                # Currently we do not support feature security policies.
                # result = rest.get_request("template/policy/vedge/definition/{}".format(policy_id))
                # if result["policyType"]=="feature":
                    # Don't support yet.
                del obj["securityPolicyId"]
        main_templates[template["templateId"]] = obj
    return {"main_templates":main_templates,"loaded_templates":loaded_templates,"policy_templates":policy_templates}
    # Backup fininshed

def restore_template(server_info,data):
    main_templates=data["main_templates"]
    loaded_templates=data["loaded_templates"]
    policy_templates=data["policy_templates"]


    # Start recovery process
    rest = ViptelaRest.init(server_info)
    # First recover the feature templates.
    result = rest.get_request("template/feature")
    exisiting_feature = [ i["templateName"] for i in result.json()["data"]]
    for uuid,temp in loaded_templates.items():
        if temp["templateName"] in exisiting_feature:
            temp["templateName"] = temp["templateName"]+"_1"
            if temp["templateName"] in exisiting_feature:
                raise Exception("ERROR : Still having name conflicts, are you running the script multiple times?")
        result = rest.post_request("template/feature/",temp)
        new_id = result.json()["templateId"]
        uuid_pairs[uuid]=new_id
    result = rest.get_request("template/policy/vedge")
    exisiting_policy = [ i["policyName"] for i in result.json()["data"]]
    for uuid,temp in policy_templates.items():
        if temp["policyName"] in exisiting_policy:
            temp["policyName"] = temp["policyName"]+"_1"
            if temp["policyName"] in exisiting_policy:
                raise Exception("ERROR : Still having name conflicts, are you running the script multiple times?")
        result = rest.post_request("template/policy/vedge/",temp)
        # For some **weird** reasons, the vManage policy API won't return policyId upon creation, so we have to use a workaround.
        # Hopefully it will be fixed soon.
        new_id = None
        if result.status_code!=200:
            result.raise_for_status()
        else:
            pl = rest.get_request("template/policy/vedge")
            pcs = pl.json()["data"]
            for tmp in pcs:
                if tmp["policyName"]==temp["policyName"]:
                    new_id = tmp["policyId"]
                    break
        if new_id:
            uuid_pairs[uuid]=new_id
        else:
            raise Exception("Policy create failed.")

    # Recover the main policies.
    result = rest.get_request("template/device")
    exisiting_main = [ i["templateName"] for i in result.json()["data"]]
    for uuid,temp in main_templates.items():
        feature = False
        if temp["templateName"] in exisiting_main:
            temp["templateName"] = temp["templateName"]+"_1"
            if temp["templateName"] in exisiting_main:
                raise Exception("ERROR : Still having name conflicts, are you running the script multiple times?")
        if temp["configType"] == "template":
            feature=True
            for sub_template in temp["generalTemplates"]:
                sub_template=update_template(sub_template)
            if "policyId" in temp and temp["policyId"]!="":
                temp["policyId"] = uuid_pairs[temp["policyId"]]
        new_temp = {
            "templateName": temp["templateName"],
            "templateDescription": temp["templateDescription"],
            "deviceType": temp["deviceType"],
            "configType": temp["configType"],
            "factoryDefault": temp["factoryDefault"]
        }
        if feature:
            if temp.get("policyId"): new_temp["policyId"]= temp["policyId"]
            else: new_temp["policyId"]=""
            if temp.get("featureTemplateUidRange"): new_temp["featureTemplateUidRange"]= temp["featureTemplateUidRange"]
            else: new_temp["featureTemplateUidRange"]=[]
            if temp.get("generalTemplates")!=None: new_temp["generalTemplates"]= temp["generalTemplates"]
            else: new_temp["generalTemplates"]=[]
            if temp.get("securityPolicyId")!=None: new_temp["securityPolicyId"]= temp["securityPolicyId"]
            else: new_temp["securityPolicyId"]=""

            result = rest.post_request("template/device/feature/",new_temp)
        else:
            new_temp["templateConfiguration"]= temp["templateConfiguration"]
            result = rest.post_request("template/device/cli/",new_temp)

        new_id = result.json()["templateId"]
        print("Created New Template {}".format(temp["templateName"]))


def transfer_template(server1,server2,template_name=None):
    resp = backup_template(server1,template_name)
    restore_template(server2,resp)



def print_help():
    print("[*] A tool for transfer templates between vManage controller.")
    print("[*] Usage:")
    print("[*] --mode : transfer/backup/restore")
    print(
        "[*]         If choosing transfer, server1 & server2's info need to be given in prompt. Otherwise just input server1's info.")
    print("[*] --all-template")
    print("[*]          If given, backup all templates in controller, can't be used with --template.")
    print("[*] --template : template name")
    print("[*]         Input template name for backup.")
    print("[*] --file : file path")
    print(
        "[*]         Input a file path to save/read file in backup & restore modes, in transfer mode this parameter is not needed.")
    print("[*] --server1-ip : Server 1's hostname")
    print("[*]         Input vManage Server1's hostname.")
    print("[*] --server1-port : Server 1's port")
    print("[*]         Input vManage Server1's port.")
    print("[*] --server1-user : Server 1's username")
    print("[*]         Input vManage Server1's username.")
    print("[*] --server1-pw : Server 1's password")
    print("[*]         Input vManage Server1's password.")
    print("[*] --server1-tenant : Server 1's tenant name")
    print("[*]         Input vManage Server1's tenant name, if not in multi tenant mode, skip this.")

    print("[*] --server2-ip : Server 2's hostname")
    print("[*]         Input vManage Server2's hostname.")
    print("[*] --server2-port : Server 2's port")
    print("[*]         Input vManage Server2's port.")
    print("[*] --server2-user : Server 2's username")
    print("[*]         Input vManage Server2's username.")
    print("[*] --server2-pw : Server 2's password")
    print("[*]         Input vManage Server2's password.")
    print("[*] --server2-tenant : Server 2's tenant name")
    print("[*]         Input vManage Server2's tenant name, if not in multi tenant mode, skip this.")
    print("[*]\n[*] Example:")
    print("[*] Transfer template test:")
    print(
        "[*] ./tools_template_backup.py --mode=transfer --template=test --server1-ip=10.0.0.1 --server1-port=443 --server1-user=admin --server1-pw=admin --server2-ip=10.0.0.2 --server2-port=443 --server2-user=admin --server2-pw=admin")
    print("[*] Backup all template:")
    print(
        "[*] ./tools_template_backup.py --mode=backup --all-template --file=backup.json --server1-ip=10.0.0.1 --server1-port=443 --server1-user=admin --server1-pw=admin")
    print("[*] Restore template from a file:")
    print(
        "[*] ./tools_template_backup.py --mode=restore --file=backup.json --server1-ip=10.0.0.1 --server1-port=443 --server1-user=admin --server1-pw=admin")


if __name__ == '__main__':


    opts, args = getopt.getopt(sys.argv[1:], '-h-s1:-u1:-pw1:-p1:-t1:-s2:-u2:-pw2:-p2:-t2:-a-t:-m:-f', ['help', 'server1-ip=', 'server1-user=', 'server1-pw=', 'server1-port=', 'server1-tenant=','server2-ip=', 'server2-user=', 'server2-pw=', 'server2-port=', 'server2-tenant=', 'all-template', 'template=','mode=','file='])

    server1_user = server2_user = server1_port = server2_port = server1_pw = server2_pw =server1_ip = server2_ip =server1_tenant =server2_tenant = all_template =template_name = mode =file = None
    for opt_name, opt_value in opts:
        if opt_name in ('-h', '--help'):
            print_help()
            exit()

        if opt_name in ('-s1', '--server1-ip'):
            server1_ip = opt_value
            print("[*] Server1 IP is {}".format(server1_ip))
        if opt_name in ('-u1', '--server1-user'):
            server1_user = opt_value
            print("[*] Server1 Username is {}".format(server1_user))
        if opt_name in ('-pw1', '--server1-pw'):
            server1_pw = opt_value
            print("[*] Server1 Password is {}".format(server1_pw))
        if opt_name in ('-p1', '--server1-port'):
            server1_port = opt_value
            print("[*] Server1 Port is {}".format(server1_port))
        if opt_name in ('-t1', '--server1-tenant'):
            server1_tenant = opt_value
            print("[*] Server1 Tenant is {}".format(server1_tenant))


        if opt_name in ('-s2', '--server2-ip'):
            server2_ip = opt_value
            print("[*] Server2 IP is {}".format(server2_ip))
        if opt_name in ('-u2', '--server2-user'):
            server2_user = opt_value
            print("[*] Server2 Username is {}".format(server2_user))
        if opt_name in ('-pw2', '--server2-pw'):
            server2_pw = opt_value
            print("[*] Server2 Password is {}".format(server2_pw))
        if opt_name in ('-p2', '--server2-port'):
            server2_port = opt_value
            print("[*] Server2 Port is {}".format(server2_port))
        if opt_name in ('-t2', '--server2-tenant'):
            server2_tenant = opt_value
            print("[*] Server2 Tenant is {}".format(server2_tenant))

        if opt_name in ('-a', '--all-template'):
            all_template=True
            print("[*] Transfering all template")
        if opt_name in ('-t', '--template'):
            all_template = False
            template_name = opt_value
            print("[*] Transfering template {}".format(template_name))

        if opt_name in ('-m', '--mode'):
            if opt_value not in ["transfer","backup","restore"]:
                print("Please enter valid modes")
                exit()
            mode = opt_value
            print("[*] Choosing mode {}".format(mode))

        if opt_name in ('-f', '--file'):
            file = opt_value
            print("[*] Choosing file {}".format(mode))
    if not (mode and (all_template or template_name or mode=="restore")):
        print("Help : Need to input mode and choose if transfering all policy or single policy.")
        print_help()
        exit()

    if mode =="transfer":

        if None in [server1_ip,server2_ip, server1_user,server2_user,server1_pw,server2_pw,server1_port,server2_port]:
            print(
                "[*] Help: Please enter the server 1 and server 2's info for transfer.")
            exit()
    elif mode =="backup":
        if None in [server1_ip, server1_user,server1_pw,server1_port,file]:
            print(
                "[*] Help: Please enter the server 1's info for backup.")
            exit()
    elif mode =="restore":
        if None in [server1_ip, server1_user,server1_pw,server1_port,file]:
            print(
                "[*] Help: Please enter the server 1's info for restore.")
            exit()

    if mode =="transfer":
        server1_info = {
        "hostname": server1_ip,
        "port": server1_port,
        "username": server1_user,
        "password": server1_pw,
        "tenant": server1_tenant
        }

        server2_info = {
        "hostname": server2_ip,
        "port": server2_port,
        "username": server2_user,
        "password": server2_pw,
        "tenant": server2_tenant
        }

        transfer_template(server1_info,server2_info,template_name)
        print("Transfer Complete.")

    elif mode =="backup":
        server1_info = {
        "hostname": server1_ip,
        "port": server1_port,
        "username": server1_user,
        "password": server1_pw,
        "tenant": server1_tenant
        }


        data = backup_template(server1_info,template_name)
        with open(file,"w") as handler:
            handler.write(json.dumps(data))

        print("Backup Complete, store at: {}".format(file))

    elif mode =="restore":

        server1_info = {
        "hostname": server1_ip,
        "port": server1_port,
        "username": server1_user,
        "password": server1_pw,
        "tenant": server1_tenant
        }

        with open(file,"r") as handler:
            json_data = handler.read()
        restore_template(server1_info,json.loads(json_data))
        print("Restore Complete")


















