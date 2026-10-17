variable "aws_region" {
  type        = string
  description = "AWS region for the MVP resources."
  default     = "us-east-1"
}

variable "project_name" {
  type        = string
  description = "Lowercase resource prefix."
  default     = "idempotent-inbox-triage"
}

variable "inbound_recipient_domain" {
  type        = string
  description = "Synthetic SES recipient domain; configure DNS and SES separately."
  default     = "inbound.example.com"
}

variable "github_repository" {
  type        = string
  description = "OWNER/REPO allowed to assume the deploy role through GitHub OIDC."
  default     = "example-org/idempotent-inbox-triage"
}
