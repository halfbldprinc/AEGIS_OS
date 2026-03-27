Name:           aegisos
Version:        0.1.0
Release:        1%{?dist}
Summary:        Linux distro integrated local AI assistant runtime
License:        Apache-2.0
BuildArch:      x86_64
Requires:       python3, python3-pip, python3-virtualenv, systemd, ffmpeg, zenity
Source0:        %{name}-%{version}.tar.gz

%description
AegisOS provides a local-first assistant runtime with installer-stage model
selection, policy-gated execution, and systemd-managed services.

%prep
%autosetup

%build
# no-op

%install
mkdir -p %{buildroot}/opt
cp -a . %{buildroot}/opt/aegisos
mkdir -p %{buildroot}/etc/systemd/system
mkdir -p %{buildroot}/etc/xdg/autostart
cp deploy/systemd/aegis-onboarding.service %{buildroot}/etc/systemd/system/aegis-onboarding.service
cp deploy/systemd/aegis-api.integrated.service %{buildroot}/etc/systemd/system/aegis-api.service
cp deploy/systemd/aegis-agent.integrated.service %{buildroot}/etc/systemd/system/aegis-agent.service
cp deploy/autostart/aegis-text-fallback.desktop %{buildroot}/etc/xdg/autostart/aegis-text-fallback.desktop

%pre
if [ -d /opt/aegisos ]; then
  bash /opt/aegisos/scripts/release_snapshot.sh --reason "rpm-pre" || true
fi

%post
getent passwd aegis >/dev/null || useradd -r -m -d /var/lib/aegis -s /sbin/nologin aegis || true
mkdir -p /etc/aegis /var/lib/aegis
cp -f /opt/aegisos/deploy/model_catalog.json /etc/aegis/model_catalog.json
touch /etc/aegis/install-selections.env
chmod 640 /etc/aegis/install-selections.env || true
bash /opt/aegisos/scripts/runtime_policy_defaults.sh /etc/aegis/runtime.env || true
python3 -m venv /opt/aegisos/.venv
/opt/aegisos/.venv/bin/python -m pip install --upgrade pip
/opt/aegisos/.venv/bin/python -m pip install "/opt/aegisos[api,llm]"
chown -R aegis:aegis /var/lib/aegis
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
  systemctl daemon-reload || true
  systemctl enable aegis-onboarding.service || true
  systemctl enable aegis-api.service || true
  systemctl enable aegis-agent.service || true
  systemctl start aegis-onboarding.service || true
  systemctl start aegis-api.service || true
  systemctl start aegis-agent.service || true
fi

%preun
if [ $1 -eq 0 ] ; then
  if command -v systemctl >/dev/null 2>&1; then
    systemctl disable --now aegis-agent.service >/dev/null 2>&1 || true
    systemctl disable --now aegis-api.service >/dev/null 2>&1 || true
    systemctl disable --now aegis-onboarding.service >/dev/null 2>&1 || true
  fi
fi

%files
/opt/aegisos
/etc/systemd/system/aegis-onboarding.service
/etc/systemd/system/aegis-api.service
/etc/systemd/system/aegis-agent.service
/etc/xdg/autostart/aegis-text-fallback.desktop

%changelog
* Thu Mar 26 2026 AegisOS Team <maintainers@aegisos.local> - 0.1.0-1
- Initial RPM packaging target for distro-integrated deployment
