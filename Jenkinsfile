pipeline {
    agent any

    parameters {
        string(name: 'BRANCH_NAME', defaultValue: 'main', description: 'Branch to deploy')
        string(name: 'TOSINLAB_AI_IP_ADDRESS', defaultValue: '192.168.0.5', description: 'IP address of the AI server')
        string(name: 'TOSINLAB_AI_SSH_USER', defaultValue: 'tfletcher', description: 'SSH username for the AI server')
        string(name: 'TOSINLAB_AI_PRIVATE_KEY_ID', defaultValue: 'tosinlab-ai-private-key', description: 'Private key ID for the AI server')
    }

    environment {
        JENKINS_JOB_WEBHOOK_URL = credentials('jenkins-job-webhook-url')
        // Set COMPOSE_PROJECT_NAME to avoid conflicts if other compose projects run nearby
        COMPOSE_PROJECT_NAME = 'docker-app-voice-studio'
        // Define the compose file path relative to the workspace root
        COMPOSE_FILE = 'docker-compose.yml'
        APP_DIR = 'apps'
    }

    stages {
        stage('Checkout') {
            steps {
                deleteDir() // clean start to avoid partial git dirs
                git branch: "${params.BRANCH_NAME}",
                    url: 'https://github.com/tosinfletcher/docker-app-voice-studio.git',
                    credentialsId: 'github-access-token'
            }
        }

        stage('Deploy to AI') {
            steps {
                sshagent([params.TOSINLAB_AI_PRIVATE_KEY_ID]) {
                    // The .env content (OMNIVOICE_API_KEY, optional HF_TOKEN)
                    // lives only in Jenkins as a secret file credential; it is
                    // written to the server at deploy time and never committed.
                    withCredentials([file(credentialsId: 'voice-studio-env-file', variable: 'ENV_FILE')]) {
                        sh """
                            set -e

                            # Copy the credential file's content into .env in the
                            # workspace (masked in logs, removed by cleanWs).
                            umask 077
                            cp "\$ENV_FILE" .env

                            # Ensure the target directory exists on the AI server.
                            ssh -o StrictHostKeyChecking=no ${params.TOSINLAB_AI_SSH_USER}@${params.TOSINLAB_AI_IP_ADDRESS} \\
                                "mkdir -p /home/${params.TOSINLAB_AI_SSH_USER}/${env.APP_DIR}/${env.COMPOSE_PROJECT_NAME}"

                            # Copy the only files the server needs: the compose
                            # file (pulls the pre-built image) and .env.
                            echo "Copying compose file + .env into ~/${env.APP_DIR}/${env.COMPOSE_PROJECT_NAME}..."
                            tar -czf - ${env.COMPOSE_FILE} .env | \\
                                ssh -o StrictHostKeyChecking=no ${params.TOSINLAB_AI_SSH_USER}@${params.TOSINLAB_AI_IP_ADDRESS} \\
                                    "tar -C /home/${params.TOSINLAB_AI_SSH_USER}/${env.APP_DIR}/${env.COMPOSE_PROJECT_NAME} -xzf -"

                            # Quoted heredoc: Jenkins values above are already
                            # inlined, and \$VAR references reach the remote shell.
                            ssh -o StrictHostKeyChecking=no ${params.TOSINLAB_AI_SSH_USER}@${params.TOSINLAB_AI_IP_ADDRESS} <<'REMOTE'
                            set -e
                            cd /home/${params.TOSINLAB_AI_SSH_USER}/${env.APP_DIR}/${env.COMPOSE_PROJECT_NAME}

                            chmod 600 .env

                            echo "Pulling the pre-built image..."
                            docker compose pull

                            echo "Starting services in detached mode..."
                            docker compose up -d --remove-orphans --force-recreate

                            # Shared AI host: prune dangling images only (never
                            # `docker image prune -a` - other services live here).
                            docker image prune -f
                            echo "[OK] Deployment steps completed"
REMOTE
                        """
                    }
                }
            }
        }

        stage('Post-Deploy check for AI') {
            steps {
                sshagent([params.TOSINLAB_AI_PRIVATE_KEY_ID]) {
                    sh """
                        echo "[+] Verifying running containers on AI server..."

                        ssh -o StrictHostKeyChecking=no ${params.TOSINLAB_AI_SSH_USER}@${params.TOSINLAB_AI_IP_ADDRESS} <<'REMOTE'
                        set -e
                        cd /home/${params.TOSINLAB_AI_SSH_USER}/${env.APP_DIR}/${env.COMPOSE_PROJECT_NAME}

                        # Run Docker Compose
                        docker compose ps

                        echo "Waiting for the backend health endpoint (first run may take a while)..."
                        ok=0
                        for i in \$(seq 1 80); do
                            if curl -sf http://localhost:3900/health >/dev/null 2>&1; then
                                ok=1
                                break
                            fi
                            sleep 15
                        done
                        if [ "\$ok" -ne 1 ]; then
                            echo "[FAIL] Backend not healthy after 20 minutes; last 200 log lines:"
                            docker compose logs --tail 200
                            exit 1
                        fi
                        echo "[OK] VoiceStudio is up: http://${params.TOSINLAB_AI_IP_ADDRESS}:3900 (API key in .env on the server)"
REMOTE
                    """
                }
            }
        }
    }

    post {
        always {
            echo 'Pipeline finished.'
            cleanWs()
        }
        success {
            echo 'Deployment successful!'
        }
        failure {
            echo 'Deployment failed.'
            // Send failure notification to pumble
            sh """
                curl -X POST -H 'Content-type: application/json' \\
                --data '{
                    "text": "Build Failed! Job: `${env.JOB_NAME}` Build: `${env.BUILD_NUMBER}`. Check logs: ${env.BUILD_URL}"
                }' \\
                ${env.JENKINS_JOB_WEBHOOK_URL}
            """
        }
    }
}
