#!/bin/bash
# One-time setup for AWS Lightsail instance (Amazon Linux 2 / ec2-user)
# Run: ssh -i bevar-ukraine-new-keypare-lightsail.pem ec2-user@3.235.159.219 'bash -s' < scripts/setup-server.sh
set -euo pipefail

echo "=== Installing Docker ==="
sudo yum update -y
sudo yum install -y docker git
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -aG docker ec2-user

echo "=== Installing Docker Compose ==="
COMPOSE_VERSION=$(curl -s https://api.github.com/repos/docker/compose/releases/latest | grep tag_name | cut -d '"' -f 4)
sudo curl -L "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
sudo ln -sf /usr/local/bin/docker-compose /usr/bin/docker-compose

# Also install compose plugin
sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -L "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

echo "=== Verifying ==="
docker --version
docker compose version || docker-compose --version

echo ""
echo "=== DONE ==="
echo "Next steps:"
echo "1. Log out and log back in (for docker group to take effect):"
echo "   exit && ssh -i bevar-ukraine-new-keypare-lightsail.pem ec2-user@3.235.159.219"
echo ""
echo "2. Clone the repo:"
echo "   git clone git@github.com:VectoraAI/bevar-ukraine-smart-email-handler-AK.git"
echo "   cd bevar-ukraine-smart-email-handler-AK"
echo ""
echo "3. Create .env file with your AWS credentials:"
echo "   cp .env.example .env"
echo "   nano .env"
echo ""
echo "4. Start the app:"
echo "   docker compose up -d --build"
echo ""
echo "5. Configure GitHub Secrets for auto-deploy (Settings > Secrets > Actions):"
echo "   LIGHTSAIL_HOST = 3.235.159.219"
echo "   LIGHTSAIL_USER = ec2-user"
echo "   LIGHTSAIL_SSH_KEY = (contents of bevar-ukraine-new-keypare-lightsail.pem)"
