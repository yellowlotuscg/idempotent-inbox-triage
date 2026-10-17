data "tls_certificate" "github" {
  url = "https://token.actions.githubusercontent.com"
}

resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.github.certificates[0].sha1_fingerprint]
}

data "aws_iam_policy_document" "github_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  name               = "${var.project_name}-github-deploy"
  assume_role_policy = data.aws_iam_policy_document.github_assume.json
}

data "aws_iam_policy_document" "github_deploy" {
  statement {
    sid = "ManageStackResources"
    actions = [
      "cloudformation:Describe*", "cloudwatch:Describe*", "dynamodb:DescribeTable", "dynamodb:ListTagsOfResource",
      "events:DescribeRule", "events:ListTargetsByRule", "iam:GetRole", "iam:ListRolePolicies", "lambda:GetFunction",
      "s3:GetBucketLocation", "s3:ListBucket", "ses:DescribeReceiptRuleSet", "sqs:GetQueueAttributes", "sqs:GetQueueUrl"
    ]
    resources = ["*"]
  }
  statement {
    sid = "ManageNamedApplicationResources"
    actions = [
      "dynamodb:CreateTable", "dynamodb:DeleteTable", "dynamodb:DescribeTable", "dynamodb:TagResource", "dynamodb:UntagResource", "dynamodb:UpdateTable", "dynamodb:UpdateTimeToLive",
      "events:DeleteRule", "events:DescribeRule", "events:ListTargetsByRule", "events:PutRule", "events:PutTargets", "events:RemoveTargets",
      "lambda:AddPermission", "lambda:CreateEventSourceMapping", "lambda:CreateFunction", "lambda:DeleteEventSourceMapping", "lambda:DeleteFunction", "lambda:DeleteFunctionConcurrency", "lambda:GetFunction", "lambda:GetPolicy", "lambda:RemovePermission", "lambda:TagResource", "lambda:UntagResource", "lambda:UpdateEventSourceMapping", "lambda:UpdateFunctionCode", "lambda:UpdateFunctionConfiguration",
      "logs:CreateLogGroup", "logs:DeleteLogGroup", "logs:DescribeLogGroups", "logs:PutRetentionPolicy",
      "s3:CreateBucket", "s3:DeleteBucket", "s3:DeleteBucketPolicy", "s3:DeleteObject", "s3:GetBucketLocation", "s3:GetBucketNotification", "s3:GetBucketPolicy", "s3:GetBucketPublicAccessBlock", "s3:GetBucketVersioning", "s3:GetEncryptionConfiguration", "s3:ListBucket", "s3:PutBucketNotification", "s3:PutBucketPolicy", "s3:PutBucketPublicAccessBlock", "s3:PutBucketVersioning", "s3:PutEncryptionConfiguration", "s3:PutObject",
      "ses:CreateReceiptRule", "ses:CreateReceiptRuleSet", "ses:DeleteReceiptRule", "ses:DeleteReceiptRuleSet", "ses:SetActiveReceiptRuleSet",
      "sqs:CreateQueue", "sqs:DeleteQueue", "sqs:GetQueueAttributes", "sqs:GetQueueUrl", "sqs:ListQueueTags", "sqs:SetQueueAttributes", "sqs:TagQueue", "sqs:UntagQueue"
    ]
    resources = [
      aws_s3_bucket.inbox.arn, "${aws_s3_bucket.inbox.arn}/*", aws_dynamodb_table.idempotency.arn,
      aws_dynamodb_table.decisions_outbox.arn, aws_sqs_queue.outbox.arn, aws_sqs_queue.outbox_dlq.arn,
      aws_lambda_function.ingest.arn, aws_lambda_function.relay.arn
    ]
  }
  statement {
    sid       = "ManageLambdaRoles"
    actions   = ["iam:CreateRole", "iam:DeleteRole", "iam:GetRole", "iam:ListRolePolicies", "iam:PassRole", "iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:TagRole", "iam:UntagRole"]
    resources = [aws_iam_role.ingest_lambda.arn, aws_iam_role.relay_lambda.arn]
  }
}

resource "aws_iam_role_policy" "github_deploy" {
  role   = aws_iam_role.github_deploy.id
  policy = data.aws_iam_policy_document.github_deploy.json
}
