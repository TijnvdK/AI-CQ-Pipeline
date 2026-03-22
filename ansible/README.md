**Note**: This installation is made for Ubuntu 24.04 LTS. It may work on other versions of Ubuntu, but it has not been tested.

# Requirements

## Install Docker

**Retrieved** from [Docker's official documentation](https://docs.docker.com/engine/install/ubuntu/):

```bash
# Add Docker's official GPG key:
sudo apt update
sudo apt install ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# Add the repository to Apt sources:
sudo tee /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt update

sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

### Make Docker executable without `sudo`

```bash
sudo groupadd docker 2>/dev/null || true
sudo usermod -aG docker $USER
newgrp docker
```

## Install GitHub CLI

**Retrieved** from [GitHub CLI's official documentation](https://github.com/cli/cli/blob/trunk/docs/install_linux.md#debian):

```bash
(type -p wget >/dev/null || (sudo apt update && sudo apt install wget -y)) \
    && sudo mkdir -p -m 755 /etc/apt/keyrings \
    && out=$(mktemp) && wget -nv -O$out https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    && cat $out | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null \
    && sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && sudo mkdir -p -m 755 /etc/apt/sources.list.d \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && sudo apt update \
    && sudo apt install gh -y
```

## Setup AWS profile

### Install AWS CLI

**Retrieved** from [AWS CLI's official documentation](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html):

```bash
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
sudo apt install unzip -y
unzip awscliv2.zip
sudo ./aws/install
```

### Configure AWS CLI with your credentials:

**Note**: Remember the profile name you use here, as you will need to set it as a secret later.

```bash
aws configure --profile default
```

## Setup Python environment

**Note**: Make sure you are in the ansible directory of the project when running these **and all following** commands.

```bash
python3 -m venv .venv
source .venv/bin/activate

pip3 install -r requirements.txt
ansible-galaxy collection install -r requirements.yaml
```

## Setup Secrets

```bash
cp /vars/secrets.yaml.example /vars/secrets.yaml
```

Replace the values in `vars/secrets.yaml` with your own secrets.<br/>
**Note**: The `github_token` should have permissions to
- Contents: Read and Write
- Issues: Read-only
- Metadata: Read-only
- Pull requests: Read and Write
- Secrets: Read and Write

```bash
ansible-vault encrypt vars/secrets.yaml
```

Remember the password you used to encrypt the file, as you will need it to run the playbook.

# Run the playbook

**Note 1**: You will be prompted for the vault password you used to encrypt the secrets file.<br/>
**Note 2**: The cleanup playbook will delete all resources created by the deployment playbook, even if there is data in them. Use with caution.

```bash
ansible-playbook playbooks/deploy_pipeline.yaml --ask-vault-password
ansible-playbook playbooks/cleanup_pipeline.yaml --ask-vault-password
```
