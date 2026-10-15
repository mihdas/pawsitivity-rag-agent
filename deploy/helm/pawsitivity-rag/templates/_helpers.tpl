{{- define "paws.name" -}}{{ .Chart.Name }}{{- end -}}
{{- define "paws.fullname" -}}
{{- if contains .Chart.Name .Release.Name -}}{{ .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else -}}{{ printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" }}{{- end -}}
{{- end -}}
{{- define "paws.labels" -}}
app.kubernetes.io/name: {{ include "paws.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}
{{- define "paws.selector" -}}
app.kubernetes.io/name: {{ include "paws.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
{{- define "paws.secretName" -}}{{ .Values.secrets.existingSecret | default (printf "%s-llm" (include "paws.fullname" .)) }}{{- end -}}
{{- define "paws.qdrantUrl" -}}
{{- if .Values.qdrant.enabled -}}http://{{ .Release.Name }}-qdrant:6333{{- else -}}{{ required "config.QDRANT_URL is required when qdrant.enabled=false" .Values.config.QDRANT_URL }}{{- end -}}
{{- end -}}
{{- define "paws.env" -}}
envFrom:
  - configMapRef:
      name: {{ include "paws.fullname" . }}
  - secretRef:
      name: {{ include "paws.secretName" . }}
{{- end -}}
