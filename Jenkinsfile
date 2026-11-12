pipeline {
    agent any

    options {
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '30'))
    }

    environment {
        TOOLS_DIR = "${WORKSPACE}/.tools"
    }

    parameters {
        string(name: 'DT_URL', defaultValue: 'http://dependency-track-apiserver-1:8080', description: 'URL API server Dependency-Track')
        string(name: 'TAG', defaultValue: '', description: 'Opsional: hanya project dengan tag ini')
        string(name: 'EXCLUDE_TYPES', defaultValue: 'golang', description: 'Jenis purl yang difilter selain paket OS, dipisah spasi')
        booleanParam(name: 'RUN_AGENT', defaultValue: true, description: 'Jalankan AI agent. Matikan untuk menguji pipeline tanpa agent')
        booleanParam(name: 'DUMP_RAW', defaultValue: false, description: 'Simpan juga data mentah semua project')
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
                sh 'rm -f radar.json unmapped.json proposals.json'
            }
        }

        stage('Siapkan tool') {
            steps {
                timeout(time: 10, unit: 'MINUTES') {
                    sh '''
                        set -e
                        python3 --version
                        command -v curl >/dev/null 2>&1 || { echo "curl tidak ditemukan di node"; exit 1; }
                        mkdir -p "$TOOLS_DIR/bin"
                        export PATH="$TOOLS_DIR/bin:$PATH"
                        if [ "$RUN_AGENT" = "true" ]; then
                            if ! command -v opencode >/dev/null 2>&1; then
                                echo "OpenCode belum ada, memasang ke $TOOLS_DIR/bin"
                                OPENCODE_INSTALL_DIR="$TOOLS_DIR/bin" curl -fsSL https://opencode.ai/install | bash
                            fi
                            opencode --version
                        fi
                    '''
                }
            }
        }

        stage('Siapkan argumen') {
            steps {
                script {
                    def args = []
                    params.EXCLUDE_TYPES.trim().split(/\s+/).findAll { it }.each {
                        if (!(it ==~ /[A-Za-z0-9_.-]+/)) { error "EXCLUDE_TYPES tidak valid: ${it}" }
                        args << "--exclude-type ${it}"
                    }
                    if (params.TAG?.trim()) {
                        if (!(params.TAG.trim() ==~ /[A-Za-z0-9_.-]+/)) { error "TAG tidak valid" }
                        args << "--tag ${params.TAG.trim()}"
                    }
                    env.RADAR_ARGS = args.join(' ')
                }
            }
        }

        stage('Dump data mentah') {
            when { expression { params.DUMP_RAW } }
            steps {
                withCredentials([string(credentialsId: 'dtrack-api-key', variable: 'DT_KEY')]) {
                    sh 'python3 dtrack_dump.py --url "$DT_URL" --out dump --with-metrics'
                }
            }
        }

        stage('Tarik data unmapped dari Dependency-Track') {
            steps {
                withCredentials([string(credentialsId: 'dtrack-api-key', variable: 'DT_KEY')]) {
                    sh 'python3 dtrack_to_radar.py --url "$DT_URL" --mapping mapping.json --out radar.json --unmapped unmapped.json $RADAR_ARGS'
                }
                script {
                    env.UNMAPPED_COUNT = sh(
                        script: "python3 -c \"import json;print(len(json.load(open('unmapped.json'))))\"",
                        returnStdout: true
                    ).trim()
                    echo "Teknologi belum terpetakan: ${env.UNMAPPED_COUNT}"
                }
            }
        }

        stage('Agent usulkan quadrant dan ring') {
            when { expression { params.RUN_AGENT && env.UNMAPPED_COUNT != '0' } }
            steps {
                catchError(buildResult: 'SUCCESS', stageResult: 'FAILURE', message: 'AI agent tidak selesai') {
                    withEnv(["PATH+TOOLS=${env.TOOLS_DIR}/bin"]) {
                        aiAgent agent: openCode(),
                                apiCredentialsId: 'OpenCode',
                                failOnAgentError: false,
                                model: 'opencode/deepseek-v4.1-flash-free',
                                prompt: '''Baca unmapped.json. Berdasarkan data tersebut, berikan usulan quadrant, ring, keyakinan, dan alasan untuk setiap teknologi.
Tulis hasilnya ke proposals.json dalam format array JSON persis seperti ini:
[
  {
    "name": "Nama Teknologi",
    "quadrant": "Languages & Frameworks",
    "ring": "Adopt",
    "alasan": "Alasan singkat penempatan.",
    "yakin": "tinggi"
  }
]
Berkas harus berisi hanya JSON array yang valid, tanpa markdown, tanpa code fence, dan tanpa teks sebelum atau sesudahnya.''',
                                yoloMode: true
                    }
                }
            }
        }

        stage('Buat radar final dari AI') {
            steps {
                sh 'python3 proposals_to_radar.py'
            }
        }
    }

    post {
        always {
            archiveArtifacts artifacts: 'radar.json, unmapped.json, proposals.json, dump/**', allowEmptyArchive: true
        }
    }
}
